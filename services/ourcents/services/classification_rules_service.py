"""Database-backed merchant alias and category rule management."""

from collections import Counter
from typing import Dict, List, Optional

from domain.classification import ClassificationEngine
from domain.deduction_rules import DeductionRules
from domain.deduplication import DuplicateDetector
from models.schema import DeductionType, ExpenseCategory
from storage.database import Database


class ClassificationRulesService:
    """Manage family-specific merchant aliases and category override rules."""

    def __init__(self, database: Database):
        self.db = database
        self.duplicate_detector = DuplicateDetector()

    def resolve_merchant_context(self, family_id: int, merchant_name: str) -> Dict:
        """Return canonical merchant data after applying an alias if one exists."""
        alias_normalized = self.duplicate_detector.normalize_merchant_name(merchant_name)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, canonical_name, canonical_normalized, priority
                FROM merchant_aliases
                WHERE family_id = ? AND alias_normalized = ? AND is_active = 1
                ORDER BY priority DESC, updated_at DESC, id DESC
                LIMIT 1
                """,
                (family_id, alias_normalized),
            )
            row = cursor.fetchone()

        if row:
            return {
                'merchant_name': row['canonical_name'],
                'merchant_normalized': row['canonical_normalized'],
                'alias_id': row['id'],
                'alias_priority': row['priority'],
            }

        return {
            'merchant_name': merchant_name,
            'merchant_normalized': alias_normalized,
            'alias_id': None,
            'alias_priority': None,
        }

    def classify_receipt(
        self,
        family_id: int,
        ai_suggestion: ExpenseCategory,
        merchant_name: str,
        item_descriptions: Optional[List[str]] = None,
    ) -> Dict:
        """Apply aliases, then family-specific rules, then the built-in classifier."""
        merchant_context = self.resolve_merchant_context(family_id, merchant_name)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, category, priority, source, notes
                FROM merchant_category_rules
                WHERE family_id = ? AND merchant_normalized = ? AND is_active = 1
                ORDER BY priority DESC, updated_at DESC, id DESC
                LIMIT 1
                """,
                (family_id, merchant_context['merchant_normalized']),
            )
            row = cursor.fetchone()

        if row:
            return {
                'merchant_name': merchant_context['merchant_name'],
                'merchant_normalized': merchant_context['merchant_normalized'],
                'category': ExpenseCategory(row['category']),
                'rule_id': row['id'],
                'rule_priority': row['priority'],
                'rule_source': row['source'],
                'rule_notes': row['notes'],
            }

        fallback_category = ClassificationEngine.refine_classification(
            ai_suggestion,
            merchant_context['merchant_name'],
            item_descriptions or [],
        )
        return {
            'merchant_name': merchant_context['merchant_name'],
            'merchant_normalized': merchant_context['merchant_normalized'],
            'category': fallback_category,
            'rule_id': None,
            'rule_priority': None,
            'rule_source': 'static',
            'rule_notes': None,
        }

    def upsert_merchant_alias(
        self,
        family_id: int,
        alias_name: str,
        canonical_name: str,
        priority: int = 100,
        created_by: Optional[int] = None,
    ) -> None:
        """Create or update a merchant alias for the family."""
        alias_normalized = self.duplicate_detector.normalize_merchant_name(alias_name)
        canonical_normalized = self.duplicate_detector.normalize_merchant_name(canonical_name)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO merchant_aliases (
                    family_id, alias_normalized, canonical_name, canonical_normalized,
                    priority, created_by, is_active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(family_id, alias_normalized)
                DO UPDATE SET canonical_name = excluded.canonical_name,
                              canonical_normalized = excluded.canonical_normalized,
                              priority = excluded.priority,
                              created_by = excluded.created_by,
                              is_active = 1,
                              updated_at = CURRENT_TIMESTAMP
                """,
                (
                    family_id,
                    alias_normalized,
                    canonical_name.strip(),
                    canonical_normalized,
                    int(priority),
                    created_by,
                ),
            )

    def upsert_category_rule(
        self,
        family_id: int,
        merchant_name: str,
        category: ExpenseCategory,
        priority: int = 100,
        created_by: Optional[int] = None,
        source: str = 'admin',
        notes: str = '',
    ) -> None:
        """Create or update a merchant category rule for the family."""
        merchant_context = self.resolve_merchant_context(family_id, merchant_name)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO merchant_category_rules (
                    family_id, merchant_normalized, merchant_display_name, category,
                    priority, source, notes, created_by, is_active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(family_id, merchant_normalized, source)
                DO UPDATE SET merchant_display_name = excluded.merchant_display_name,
                              category = excluded.category,
                              priority = excluded.priority,
                              notes = excluded.notes,
                              created_by = excluded.created_by,
                              is_active = 1,
                              updated_at = CURRENT_TIMESTAMP
                """,
                (
                    family_id,
                    merchant_context['merchant_normalized'],
                    merchant_context['merchant_name'],
                    category.value,
                    int(priority),
                    source,
                    notes.strip() or None,
                    created_by,
                ),
            )

    def record_feedback_rule(
        self,
        family_id: int,
        merchant_name: str,
        category: ExpenseCategory,
        created_by: Optional[int] = None,
    ) -> None:
        """Persist a strong learned category rule from receipt confirmation."""
        self.upsert_category_rule(
            family_id=family_id,
            merchant_name=merchant_name,
            category=category,
            priority=200,
            created_by=created_by,
            source='feedback',
            notes='Learned from pending receipt confirmation',
        )

    def list_merchant_aliases(self, family_id: int) -> List[Dict]:
        """List active aliases configured for the family."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, alias_normalized, canonical_name, canonical_normalized,
                       priority, created_by, created_at, updated_at
                FROM merchant_aliases
                WHERE family_id = ? AND is_active = 1
                ORDER BY priority DESC, alias_normalized ASC
                """,
                (family_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def list_category_rules(self, family_id: int) -> List[Dict]:
        """List active merchant category rules configured for the family."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, merchant_display_name, merchant_normalized, category,
                       priority, source, notes, created_by, created_at, updated_at
                FROM merchant_category_rules
                WHERE family_id = ? AND is_active = 1
                ORDER BY priority DESC, merchant_display_name ASC, source ASC
                """,
                (family_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def delete_merchant_alias(self, family_id: int, alias_id: int) -> None:
        """Soft-delete a merchant alias."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE merchant_aliases
                SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND family_id = ?
                """,
                (alias_id, family_id),
            )

    def delete_category_rule(self, family_id: int, rule_id: int) -> None:
        """Soft-delete a merchant category rule."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE merchant_category_rules
                SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND family_id = ?
                """,
                (rule_id, family_id),
            )

    def preview_reclassification(self, family_id: int) -> Dict:
        """Preview how existing active receipts would change under current rules."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT r.id, r.merchant_name, r.merchant_normalized, r.category, r.status,
                       rd.deduction_type, rd.evidence_text
                FROM receipts r
                LEFT JOIN receipt_deductions rd ON rd.receipt_id = r.id
                WHERE r.family_id = ?
                  AND r.status IN ('pending', 'confirmed', 'duplicate_suspected')
                ORDER BY r.purchase_date DESC, r.id DESC
                """,
                (family_id,),
            )
            receipts = [dict(row) for row in cursor.fetchall()]

            changes = []
            for receipt in receipts:
                item_descriptions = self._get_receipt_item_descriptions(conn, receipt['id'])
                classification_result = self.classify_receipt(
                    family_id,
                    ExpenseCategory(receipt['category']),
                    receipt['merchant_name'],
                    item_descriptions,
                )

                merchant_changed = classification_result['merchant_name'] != receipt['merchant_name']
                category_changed = classification_result['category'].value != receipt['category']

                if merchant_changed or category_changed:
                    changes.append(
                        {
                            'receipt_id': receipt['id'],
                            'status': receipt['status'],
                            'current_merchant_name': receipt['merchant_name'],
                            'new_merchant_name': classification_result['merchant_name'],
                            'current_category': receipt['category'],
                            'new_category': classification_result['category'].value,
                            'rule_source': classification_result['rule_source'],
                        }
                    )

        return {
            'total_active_receipts': len(receipts),
            'changed_receipts': len(changes),
            'changes': changes,
            'by_new_category': dict(Counter(change['new_category'] for change in changes)),
        }

    def apply_reclassification(self, family_id: int, user_id: Optional[int] = None) -> Dict:
        """Apply aliases and category rules to existing active receipts for the family."""
        preview = self.preview_reclassification(family_id)
        updated = []

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            for change in preview['changes']:
                item_descriptions = self._get_receipt_item_descriptions(conn, change['receipt_id'])

                cursor.execute(
                    """
                    UPDATE receipts
                    SET merchant_name = ?,
                        merchant_normalized = ?,
                        category = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND family_id = ?
                    """,
                    (
                        change['new_merchant_name'],
                        self.duplicate_detector.normalize_merchant_name(change['new_merchant_name']),
                        change['new_category'],
                        change['receipt_id'],
                        family_id,
                    ),
                )

                self._refresh_deduction_for_receipt(
                    conn=conn,
                    receipt_id=change['receipt_id'],
                    merchant_name=change['new_merchant_name'],
                    category=ExpenseCategory(change['new_category']),
                    item_descriptions=item_descriptions,
                )

                cursor.execute(
                    """
                    INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        'reclassify',
                        'receipt',
                        change['receipt_id'],
                        f"Batch reclassified merchant from {change['current_merchant_name']} to {change['new_merchant_name']}; "
                        f"category from {change['current_category']} to {change['new_category']}",
                    ),
                )

                updated.append(change)

        return {
            'updated_receipts': len(updated),
            'changes': updated,
            'by_new_category': dict(Counter(change['new_category'] for change in updated)),
        }

    def _get_receipt_item_descriptions(self, conn, receipt_id: int) -> List[str]:
        """Return item descriptions for a receipt using an existing connection."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT description
            FROM receipt_items
            WHERE receipt_id = ?
            ORDER BY id ASC
            """,
            (receipt_id,),
        )
        return [row['description'] for row in cursor.fetchall()]

    def _refresh_deduction_for_receipt(
        self,
        conn,
        receipt_id: int,
        merchant_name: str,
        category: ExpenseCategory,
        item_descriptions: List[str],
    ) -> None:
        """Re-evaluate deduction metadata after reclassification."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT total_amount
            FROM receipts
            WHERE id = ?
            """,
            (receipt_id,),
        )
        receipt = cursor.fetchone()
        if receipt is None:
            return

        cursor.execute(
            """
            SELECT deduction_type, evidence_text
            FROM receipt_deductions
            WHERE receipt_id = ?
            """,
            (receipt_id,),
        )
        existing = cursor.fetchone()
        ai_suggestion = DeductionType(existing['deduction_type']) if existing else DeductionType.NONE
        ai_evidence = existing['evidence_text'] if existing else ''

        is_deductible, deduction_type, evidence, evidence_level = DeductionRules.evaluate_deduction(
            category,
            merchant_name,
            item_descriptions,
            ai_suggestion,
            ai_evidence,
        )
        deduction_amount = receipt['amount'] if is_deductible else 0.0
        deduction_amount = receipt['total_amount'] if is_deductible else 0.0

        cursor.execute(
            """
            UPDATE receipt_deductions
            SET is_deductible = ?,
                deduction_type = ?,
                evidence_text = ?,
                evidence_level = ?,
                amount = ?,
                notes = COALESCE(notes, 'Updated during batch reclassification')
            WHERE receipt_id = ?
            """,
            (
                is_deductible,
                deduction_type.value,
                evidence,
                evidence_level.value,
                deduction_amount,
                receipt_id,
            ),
        )