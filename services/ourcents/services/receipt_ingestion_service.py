"""
Receipt ingestion service - orchestrates upload, AI extraction, deduplication, and storage.
"""

import logging
import os
from typing import Tuple, Optional, List
from datetime import date, datetime
from models.schema import (
    DeductionType,
    ExpenseCategory,
    ReceiptStatus,
    ReceiptItemData,
)
from storage.database import Database
from storage.file_storage import FileStorage
from services.ai import get_ai_provider
from services.classification_rules_service import ClassificationRulesService
from domain.deduplication import DuplicateDetector
from domain.deduction_rules import DeductionRules


logger = logging.getLogger(__name__)


def _normalize_purchase_date_for_storage(purchase_date: datetime) -> str:
    """Persist receipt purchase dates as YYYY-MM-DD for stable SQLite date queries."""
    return purchase_date.date().isoformat()


class ReceiptIngestionService:
    """Service for processing and ingesting receipt uploads."""
    
    def __init__(self, database: Database, file_storage: FileStorage):
        """
        Initialize ingestion service.
        
        Args:
            database: Database instance
            file_storage: File storage instance
        """
        self.db = database
        self.storage = file_storage
        self.ai_provider = get_ai_provider()
        self.duplicate_detector = DuplicateDetector()
        self.classification_rules = ClassificationRulesService(database)
    
    async def process_receipt_upload(
        self,
        family_id: int,
        user_id: int,
        file_content: bytes,
        filename: str,
        mime_type: str,
    ) -> Tuple[str, Optional[int], Optional[dict]]:
        """
        Process uploaded receipt through full ingestion pipeline.
        
        Args:
            family_id: Family identifier
            user_id: User identifier
            file_content: Binary file content
            filename: Original filename
            mime_type: File MIME type
            
        Returns:
            Tuple of (status, receipt_id, duplicate_info)
            - status: 'success', 'duplicate_hash', 'duplicate_semantic', 'failed'
            - receipt_id: ID of created receipt (if success)
            - duplicate_info: Information about duplicate if found
        """
        logger.info(
            "Starting receipt upload family_id=%s user_id=%s filename=%s mime_type=%s",
            family_id,
            user_id,
            filename,
            mime_type,
        )

        # Step 1: Compute file hash
        file_hash = self.storage.compute_file_hash(file_content)
        logger.info("Computed receipt hash filename=%s hash=%s", filename, file_hash[:12])
        
        # Step 2: Check for hash-based duplicate
        if self._check_hash_duplicate(file_hash, family_id):
            logger.warning("Hash duplicate detected filename=%s family_id=%s", filename, family_id)
            return 'duplicate_hash', None, {'reason': 'Identical file already uploaded'}
        
        # Step 3: Save to temporary storage
        temp_path, _ = self.storage.save_temp_file(file_content, filename)
        logger.info("Stored temporary upload filename=%s temp_path=%s", filename, temp_path)
        
        try:
            # Step 4: Extract data using AI.
            extraction_result = await self.ai_provider.extract_receipt_data(file_content, mime_type)

            item_descriptions = [item.description for item in extraction_result.items]
            classification_result = self.classification_rules.classify_receipt(
                family_id,
                extraction_result.category_suggestion,
                extraction_result.merchant_name,
                item_descriptions,
            )
            effective_merchant_name = classification_result['merchant_name']
            merchant_normalized = classification_result['merchant_normalized']

            logger.info(
                "AI extraction finished filename=%s merchant=%s resolved_merchant=%s amount=%s confidence=%.2f rule_source=%s",
                filename,
                extraction_result.merchant_name,
                effective_merchant_name,
                extraction_result.total_amount,
                extraction_result.confidence_score,
                classification_result['rule_source'],
            )
            
            # Step 6: Check for semantic duplicates
            semantic_duplicates = self._find_semantic_duplicates(
                family_id,
                merchant_normalized,
                extraction_result.purchase_date,
                extraction_result.total_amount
            )
            
            if semantic_duplicates:
                logger.warning(
                    "Semantic duplicate detected filename=%s candidates=%s",
                    filename,
                    len(semantic_duplicates),
                )
                receipt_id, storage_path = self._save_receipt(
                    family_id=family_id,
                    user_id=user_id,
                    filename=filename,
                    file_hash=file_hash,
                    file_size=len(file_content),
                    mime_type=mime_type,
                    temp_path=temp_path,
                    merchant_name=effective_merchant_name,
                    merchant_normalized=merchant_normalized,
                    purchase_date=extraction_result.purchase_date,
                    total_amount=extraction_result.total_amount,
                    currency=extraction_result.currency,
                    category=classification_result['category'],
                    confidence_score=extraction_result.confidence_score,
                    items=extraction_result.items,
                    is_deductible=extraction_result.tax_deductible,
                    deduction_type=extraction_result.deduction_type,
                    deduction_evidence=extraction_result.deduction_evidence,
                    evidence_level=extraction_result.evidence_level,
                    deduction_amount=extraction_result.total_amount if extraction_result.tax_deductible else 0.0,
                    status=ReceiptStatus.DUPLICATE_SUSPECTED,
                )

                return 'duplicate_semantic', receipt_id, {
                    'reason': 'Similar receipt found',
                    'duplicates': semantic_duplicates,
                    'extraction': self._serialize_extraction_result(extraction_result),
                    'storage_path': storage_path,
                    'extraction_method': 'ai',
                }
            
            # Step 7: Apply configurable classification result.
            final_category = classification_result['category']
            
            # Step 8: Evaluate tax deduction
            is_deductible, deduction_type, evidence, evidence_level = \
                DeductionRules.evaluate_deduction(
                    final_category,
                    effective_merchant_name,
                    item_descriptions,
                    extraction_result.deduction_type,
                    extraction_result.deduction_evidence
                )
            
            # Step 9: Save to database
            receipt_id, storage_path = self._save_receipt(
                family_id=family_id,
                user_id=user_id,
                filename=filename,
                file_hash=file_hash,
                file_size=len(file_content),
                mime_type=mime_type,
                temp_path=temp_path,
                merchant_name=effective_merchant_name,
                merchant_normalized=merchant_normalized,
                purchase_date=extraction_result.purchase_date,
                total_amount=extraction_result.total_amount,
                currency=extraction_result.currency,
                category=final_category,
                confidence_score=extraction_result.confidence_score,
                items=extraction_result.items,
                is_deductible=is_deductible,
                deduction_type=deduction_type,
                deduction_evidence=evidence,
                evidence_level=evidence_level,
                deduction_amount=extraction_result.total_amount if is_deductible else 0.0,
                status=ReceiptStatus.PENDING,
            )

            logger.info("Receipt saved as pending receipt_id=%s filename=%s", receipt_id, filename)

            return 'pending_confirmation', receipt_id, {
                'extraction': self._serialize_extraction_result(extraction_result),
                'storage_path': storage_path,
                'extraction_method': 'ai',
            }
            
        except Exception as e:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logger.exception("Receipt processing failed filename=%s", filename)
            raise RuntimeError(f"Receipt processing failed: {str(e)}")

    def _check_hash_duplicate(self, file_hash: str, family_id: int) -> bool:
        """Check if file hash already exists for this family."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM upload_files WHERE content_hash = ? AND family_id = ?",
                (file_hash, family_id)
            )
            return cursor.fetchone() is not None
    
    def _find_semantic_duplicates(
        self,
        family_id: int,
        merchant_normalized: str,
        purchase_date: datetime,
        total_amount: float,
        exclude_receipt_id: Optional[int] = None,
    ) -> List[dict]:
        """Find semantic duplicate candidates."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT id, merchant_name, merchant_normalized, purchase_date, total_amount
                FROM receipts
                WHERE family_id = ? AND merchant_normalized = ?
            """
            params = [family_id, merchant_normalized]

            if exclude_receipt_id is not None:
                query += " AND id != ?"
                params.append(exclude_receipt_id)

            query += """
                ORDER BY purchase_date DESC
                LIMIT 10
            """
            cursor.execute(query, params)
            
            existing = [dict(row) for row in cursor.fetchall()]
            
            return self.duplicate_detector.find_semantic_duplicates(
                merchant_normalized,
                purchase_date,
                total_amount,
                existing
            )

    def get_receipt_details(self, family_id: int, receipt_id: int) -> Optional[dict]:
        """Return receipt details, items, and deduction metadata."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.id, r.family_id, r.user_id, r.upload_file_id, r.merchant_name,
                       r.merchant_normalized, r.purchase_date, r.total_amount, r.currency,
                       r.category, r.status, r.confidence_score, r.notes, r.created_at,
                       uf.filename, uf.storage_path, u.username
                FROM receipts r
                JOIN upload_files uf ON uf.id = r.upload_file_id
                JOIN users u ON u.id = r.user_id
                WHERE r.family_id = ? AND r.id = ?
            """, (family_id, receipt_id))
            receipt = cursor.fetchone()

            if receipt is None:
                return None

            cursor.execute("""
                SELECT description, quantity, unit_price, total_price, category
                FROM receipt_items
                WHERE receipt_id = ?
                ORDER BY id ASC
            """, (receipt_id,))
            items = [dict(row) for row in cursor.fetchall()]

            cursor.execute("""
                SELECT is_deductible, deduction_type, evidence_text, evidence_level, amount, notes
                FROM receipt_deductions
                WHERE receipt_id = ?
            """, (receipt_id,))
            deduction = cursor.fetchone()

            details = dict(receipt)
            details['items'] = items
            details['deduction'] = dict(deduction) if deduction else None
            return details

    def update_receipt_status(
        self,
        family_id: int,
        receipt_id: int,
        new_status: ReceiptStatus,
        notes: Optional[str] = None,
    ) -> None:
        """Update receipt status for confirmation workflow."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE receipts
                SET status = ?,
                    notes = COALESCE(?, notes),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND family_id = ?
            """, (new_status.value, notes, receipt_id, family_id))
            logger.info(
                "Updated receipt status receipt_id=%s family_id=%s new_status=%s",
                receipt_id,
                family_id,
                new_status.value,
            )

    def delete_receipt(
        self,
        family_id: int,
        receipt_id: int,
        acting_user_id: int,
    ) -> dict:
        """Delete a receipt and its stored image. Only family admins may perform this action."""
        if not self._is_family_admin(acting_user_id, family_id):
            raise ValueError("Only admins can delete receipts")

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT r.id, r.merchant_name, r.purchase_date, r.total_amount, r.currency,
                       r.status, uf.id AS upload_file_id, uf.storage_path
                FROM receipts r
                JOIN upload_files uf ON uf.id = r.upload_file_id
                WHERE r.id = ? AND r.family_id = ?
                """,
                (receipt_id, family_id),
            )
            receipt = cursor.fetchone()

            if receipt is None:
                raise ValueError("Receipt not found")

            cursor.execute("DELETE FROM receipt_items WHERE receipt_id = ?", (receipt_id,))
            cursor.execute("DELETE FROM receipt_deductions WHERE receipt_id = ?", (receipt_id,))
            cursor.execute("DELETE FROM receipts WHERE id = ? AND family_id = ?", (receipt_id, family_id))
            cursor.execute("DELETE FROM upload_files WHERE id = ? AND family_id = ?", (receipt['upload_file_id'], family_id))
            cursor.execute(
                """
                INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    acting_user_id,
                    'delete',
                    'receipt',
                    receipt_id,
                    f"Deleted receipt from merchant={receipt['merchant_name']}",
                ),
            )

        if receipt['storage_path']:
            self.storage.delete_file(receipt['storage_path'])

        logger.warning(
            "Deleted receipt receipt_id=%s family_id=%s by_user=%s merchant=%s",
            receipt_id,
            family_id,
            acting_user_id,
            receipt['merchant_name'],
        )

        return {
            'receipt_id': receipt['id'],
            'merchant_name': receipt['merchant_name'],
            'purchase_date': receipt['purchase_date'],
            'total_amount': receipt['total_amount'],
            'currency': receipt['currency'],
            'status': receipt['status'],
        }

    def confirm_receipt(
        self,
        family_id: int,
        receipt_id: int,
        merchant_name: str,
        purchase_date_value: date,
        total_amount: float,
        category: ExpenseCategory,
        is_deductible: bool,
        deduction_type: DeductionType,
        deduction_evidence: str,
        items: Optional[List[dict]],
        notes: str,
    ) -> None:
        """Persist edited receipt fields and mark the receipt as confirmed."""
        merchant_normalized = self.duplicate_detector.normalize_merchant_name(merchant_name)
        deduction_amount = total_amount if is_deductible else 0.0
        effective_deduction_type = deduction_type if is_deductible else DeductionType.NONE

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE receipts
                SET merchant_name = ?,
                    merchant_normalized = ?,
                    purchase_date = ?,
                    total_amount = ?,
                    category = ?,
                    status = ?,
                    notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND family_id = ?
            """, (
                merchant_name,
                merchant_normalized,
                purchase_date_value.isoformat(),
                total_amount,
                category.value,
                ReceiptStatus.CONFIRMED.value,
                notes or None,
                receipt_id,
                family_id,
            ))

            cursor.execute("""
                UPDATE receipt_deductions
                SET is_deductible = ?,
                    deduction_type = ?,
                    evidence_text = ?,
                    amount = ?,
                    notes = ?
                WHERE receipt_id = ?
            """, (
                is_deductible,
                effective_deduction_type.value,
                deduction_evidence,
                deduction_amount,
                notes or None,
                receipt_id,
            ))

            if items is not None:
                cursor.execute("DELETE FROM receipt_items WHERE receipt_id = ?", (receipt_id,))
                for item in items:
                    item_description = str(item.get('description') or '').strip()
                    if not item_description:
                        continue

                    item_quantity = float(item.get('quantity') or 1.0)
                    item_unit_price_raw = item.get('unit_price')
                    item_unit_price = float(item_unit_price_raw) if item_unit_price_raw not in (None, '') else None
                    item_total_price = float(item.get('total_price') or 0.0)
                    item_category_value = item.get('category') or ExpenseCategory.OTHER.value

                    cursor.execute("""
                        INSERT INTO receipt_items (receipt_id, description, quantity, unit_price, total_price, category)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        receipt_id,
                        item_description,
                        item_quantity,
                        item_unit_price,
                        item_total_price,
                        ExpenseCategory(item_category_value).value,
                    ))

            cursor.execute("""
                INSERT INTO audit_logs (action, entity_type, entity_id, details)
                VALUES (?, ?, ?, ?)
            """, (
                'confirm',
                'receipt',
                receipt_id,
                f'Confirmed receipt with edited merchant={merchant_name} total_amount={total_amount}',
            ))

            logger.info(
                "Confirmed receipt receipt_id=%s family_id=%s merchant=%s amount=%s category=%s deductible=%s",
                receipt_id,
                family_id,
                merchant_name,
                total_amount,
                category.value,
                is_deductible,
            )

        try:
            self.classification_rules.record_feedback_rule(
                family_id=family_id,
                merchant_name=merchant_name,
                category=category,
                created_by=None,
            )
        except Exception:
            logger.exception(
                "Failed to record classification feedback receipt_id=%s family_id=%s merchant=%s",
                receipt_id,
                family_id,
                merchant_name,
            )
    
    def _save_receipt(
        self,
        family_id: int,
        user_id: int,
        filename: str,
        file_hash: str,
        file_size: int,
        mime_type: str,
        temp_path: str,
        merchant_name: str,
        merchant_normalized: str,
        purchase_date: datetime,
        total_amount: float,
        currency: str,
        category,
        confidence_score: float,
        items: List[ReceiptItemData],
        is_deductible: bool,
        deduction_type,
        deduction_evidence: str,
        evidence_level,
        deduction_amount: float,
        status: ReceiptStatus,
    ) -> Tuple[int, str]:
        """Save receipt and related data to database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Insert upload file record
            cursor.execute("""
                INSERT INTO upload_files (family_id, user_id, filename, content_hash, 
                                        file_size, mime_type, storage_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (family_id, user_id, filename, file_hash, file_size, mime_type, ''))
            
            upload_id = cursor.lastrowid
            
            # Determine storage path and move file
            extension = filename.rsplit('.', 1)[-1] if '.' in filename else 'jpg'
            storage_path = self.storage.get_storage_path(
                family_id, upload_id, file_hash, extension
            )
            self.storage.move_from_temp(temp_path, storage_path)
            
            # Update storage path
            cursor.execute(
                "UPDATE upload_files SET storage_path = ? WHERE id = ?",
                (storage_path, upload_id)
            )
            
            # Insert receipt record
            cursor.execute("""
                INSERT INTO receipts (family_id, user_id, upload_file_id, merchant_name,
                                    merchant_normalized, purchase_date, total_amount, currency,
                                    category, status, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (family_id, user_id, upload_id, merchant_name, merchant_normalized,
                  _normalize_purchase_date_for_storage(purchase_date), total_amount, currency, category.value,
                  status.value, confidence_score))
            
            receipt_id = cursor.lastrowid
            
            # Insert items
            for item in items:
                cursor.execute("""
                    INSERT INTO receipt_items (receipt_id, description, quantity,
                                             unit_price, total_price, category)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (receipt_id, item.description, item.quantity, item.unit_price,
                      item.total_price, item.category.value))
            
            # Insert deduction record
            cursor.execute("""
                INSERT INTO receipt_deductions (receipt_id, is_deductible, deduction_type,
                                              evidence_text, evidence_level, amount)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (receipt_id, is_deductible, deduction_type.value, deduction_evidence,
                  evidence_level.value, deduction_amount))
            
            # Log action
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, 'create', 'receipt', receipt_id, 
                  f"Uploaded receipt from {merchant_name} with status {status.value}"))
            
            conn.commit()
            return receipt_id, storage_path

    def _serialize_extraction_result(self, extraction_result) -> dict:
        """Convert extraction result into JSON-safe preview data."""
        data = extraction_result.model_dump(mode='json')
        data['purchase_date'] = extraction_result.purchase_date.isoformat()
        return data

    def _is_family_admin(self, user_id: int, family_id: int) -> bool:
        """Return whether the user is an admin in the target family."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT role FROM family_members
                WHERE user_id = ? AND family_id = ?
                """,
                (user_id, family_id),
            )
            row = cursor.fetchone()
            return row is not None and row['role'] == 'admin'
