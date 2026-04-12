"""
Deduplication logic for receipt processing.
"""

from typing import Optional, List, Tuple
from datetime import datetime, timedelta
import re


class DuplicateDetector:
    """Handles duplicate receipt detection."""
    
    @staticmethod
    def normalize_merchant_name(merchant_name: str) -> str:
        """
        Normalize merchant name for comparison.
        
        Args:
            merchant_name: Raw merchant name
            
        Returns:
            Normalized merchant name
        """
        # Convert to lowercase
        normalized = merchant_name.lower().strip()
        
        # Remove common suffixes
        suffixes = [
            r'\s+inc\.?$', r'\s+llc\.?$', r'\s+ltd\.?$', 
            r'\s+corp\.?$', r'\s+co\.?$', r'\s+store.*$'
        ]
        for suffix in suffixes:
            normalized = re.sub(suffix, '', normalized)
        
        # Remove special characters except spaces
        normalized = re.sub(r'[^a-z0-9\s]', '', normalized)
        
        # Collapse multiple spaces
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized.strip()
    
    @staticmethod
    def check_hash_duplicate(file_hash: str, existing_hashes: List[str]) -> bool:
        """
        Check if file hash already exists.
        
        Args:
            file_hash: Hash of uploaded file
            existing_hashes: List of existing file hashes
            
        Returns:
            True if duplicate found
        """
        return file_hash in existing_hashes
    
    @staticmethod
    def find_semantic_duplicates(
        merchant_normalized: str,
        purchase_date: datetime,
        total_amount: float,
        existing_receipts: List[dict],
        date_tolerance_days: int = 1,
        amount_tolerance_percent: float = 0.01
    ) -> List[dict]:
        """
        Find potential semantic duplicates based on merchant, date, and amount.
        
        Args:
            merchant_normalized: Normalized merchant name
            purchase_date: Purchase date
            total_amount: Total amount
            existing_receipts: List of existing receipt dictionaries
            date_tolerance_days: Days before/after to consider
            amount_tolerance_percent: Percentage difference to allow (e.g., 0.01 = 1%)
            
        Returns:
            List of potentially duplicate receipts
        """
        duplicates = []
        
        date_min = purchase_date - timedelta(days=date_tolerance_days)
        date_max = purchase_date + timedelta(days=date_tolerance_days)
        amount_tolerance = total_amount * amount_tolerance_percent
        
        for receipt in existing_receipts:
            # Check merchant match
            if receipt['merchant_normalized'] != merchant_normalized:
                continue
            
            # Check date within tolerance
            receipt_date = receipt['purchase_date']
            if isinstance(receipt_date, str):
                receipt_date = datetime.fromisoformat(receipt_date.replace('Z', '+00:00'))
            
            if not (date_min <= receipt_date <= date_max):
                continue
            
            # Check amount within tolerance
            amount_diff = abs(receipt['total_amount'] - total_amount)
            if amount_diff > amount_tolerance:
                continue
            
            duplicates.append(receipt)
        
        return duplicates
    
    @staticmethod
    def calculate_similarity_score(
        merchant1: str,
        date1: datetime,
        amount1: float,
        merchant2: str,
        date2: datetime,
        amount2: float
    ) -> float:
        """
        Calculate similarity score between two receipts.
        
        Args:
            merchant1, merchant2: Merchant names
            date1, date2: Purchase dates
            amount1, amount2: Total amounts
            
        Returns:
            Similarity score from 0.0 to 1.0
        """
        score = 0.0
        
        # Merchant match (40%)
        if merchant1 == merchant2:
            score += 0.4
        
        # Date match (30%)
        date_diff = abs((date1 - date2).total_seconds())
        if date_diff == 0:
            score += 0.3
        elif date_diff < 86400:  # Same day
            score += 0.2
        elif date_diff < 172800:  # Within 2 days
            score += 0.1
        
        # Amount match (30%)
        if amount1 > 0:
            amount_diff_percent = abs(amount1 - amount2) / amount1
            if amount_diff_percent < 0.01:
                score += 0.3
            elif amount_diff_percent < 0.05:
                score += 0.2
            elif amount_diff_percent < 0.10:
                score += 0.1
        
        return score
