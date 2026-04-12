"""
Tax deduction rules and eligibility logic.
"""

from models.schema import DeductionType, EvidenceLevel, ExpenseCategory
from typing import Tuple, Dict
import re


class DeductionRules:
    """Handles tax deduction eligibility determination."""
    
    # Category-based deduction rules
    CATEGORY_DEDUCTION_MAP = {
        ExpenseCategory.HEALTHCARE: {
            'type': DeductionType.MEDICAL,
            'base_eligibility': True,
            'evidence_level': EvidenceLevel.HIGH
        },
        ExpenseCategory.EDUCATION: {
            'type': DeductionType.EDUCATION,
            'base_eligibility': True,
            'evidence_level': EvidenceLevel.MEDIUM
        },
        ExpenseCategory.TOOLS: {
            'type': DeductionType.BUSINESS,
            'base_eligibility': False,  # Depends on business use
            'evidence_level': EvidenceLevel.MEDIUM
        },
        ExpenseCategory.UTILITIES: {
            'type': DeductionType.HOME_OFFICE,
            'base_eligibility': False,  # Depends on home office
            'evidence_level': EvidenceLevel.MEDIUM
        }
    }
    
    # Keyword patterns for deduction evidence
    DEDUCTION_KEYWORDS = {
        DeductionType.MEDICAL: [
            'prescription', 'medicine', 'doctor', 'hospital',
            'dental', 'vision', 'therapy', 'medical',
            'health insurance', 'co-pay', 'copay'
        ],
        DeductionType.BUSINESS: [
            'office supply', 'business', 'professional',
            'conference', 'seminar', 'subscription',
            'software', 'equipment', 'tool'
        ],
        DeductionType.HOME_OFFICE: [
            'internet', 'electricity', 'office furniture',
            'desk', 'chair', 'computer', 'monitor'
        ],
        DeductionType.CHARITABLE: [
            'donation', 'charity', 'nonprofit', 'foundation',
            'contribution', 'gift', 'volunteer'
        ],
        DeductionType.EDUCATION: [
            'tuition', 'textbook', 'course', 'training',
            'certification', 'seminar', 'school'
        ]
    }
    
    # Merchant patterns that strongly indicate deductibility
    DEDUCTIBLE_MERCHANT_PATTERNS = {
        DeductionType.MEDICAL: [
            r'.*\b(pharmacy|cvs|walgreens|clinic|hospital|doctor|dentist)\b.*'
        ],
        DeductionType.CHARITABLE: [
            r'.*\b(goodwill|salvation army|red cross|charity)\b.*'
        ],
        DeductionType.EDUCATION: [
            r'.*\b(university|college|school|academy|bookstore)\b.*'
        ]
    }
    
    @classmethod
    def evaluate_deduction(
        cls,
        category: ExpenseCategory,
        merchant_name: str,
        item_descriptions: list = None,
        ai_suggestion: DeductionType = None,
        ai_evidence: str = ""
    ) -> Tuple[bool, DeductionType, str, EvidenceLevel]:
        """
        Evaluate whether an expense is tax deductible.
        
        Args:
            category: Expense category
            merchant_name: Merchant name
            item_descriptions: Optional item descriptions
            ai_suggestion: AI-suggested deduction type
            ai_evidence: AI-provided evidence text
            
        Returns:
            Tuple of (is_deductible, deduction_type, evidence, evidence_level)
        """
        merchant_lower = merchant_name.lower()
        
        # Start with AI suggestion if provided
        deduction_type = ai_suggestion or DeductionType.NONE
        evidence_parts = [ai_evidence] if ai_evidence else []
        evidence_level = EvidenceLevel.NONE
        is_deductible = False
        
        # Check merchant patterns for strong matches
        for deduction, patterns in cls.DEDUCTIBLE_MERCHANT_PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, merchant_lower):
                    is_deductible = True
                    deduction_type = deduction
                    evidence_level = EvidenceLevel.HIGH
                    evidence_parts.append(f"Merchant '{merchant_name}' commonly associated with {deduction.value} expenses")
                    return is_deductible, deduction_type, '; '.join(evidence_parts), evidence_level
        
        # Check category-based rules
        if category in cls.CATEGORY_DEDUCTION_MAP:
            rule = cls.CATEGORY_DEDUCTION_MAP[category]
            if rule['base_eligibility']:
                is_deductible = True
                deduction_type = rule['type']
                evidence_level = rule['evidence_level']
                evidence_parts.append(f"Category '{category.value}' typically eligible for {deduction_type.value} deduction")
        
        # Search for deduction keywords in merchant name and items
        keyword_matches = cls._find_keyword_matches(
            merchant_lower,
            item_descriptions or []
        )
        
        if keyword_matches:
            best_match = max(keyword_matches, key=keyword_matches.get)
            match_count = keyword_matches[best_match]
            
            if match_count >= 2:  # Strong evidence
                is_deductible = True
                deduction_type = best_match
                evidence_level = EvidenceLevel.HIGH
                evidence_parts.append(f"Multiple indicators for {best_match.value} deduction")
            elif match_count == 1:  # Moderate evidence
                if not is_deductible:  # Only use if no stronger evidence
                    is_deductible = True
                    deduction_type = best_match
                    evidence_level = EvidenceLevel.MEDIUM
                    evidence_parts.append(f"Possible {best_match.value} deduction")
        
        # If no evidence found, mark as not deductible
        if not evidence_parts:
            is_deductible = False
            deduction_type = DeductionType.NONE
            evidence_level = EvidenceLevel.NONE
            evidence_parts.append("No deduction indicators found")
        
        return is_deductible, deduction_type, '; '.join(evidence_parts), evidence_level
    
    @classmethod
    def _find_keyword_matches(
        cls,
        merchant_lower: str,
        item_descriptions: list
    ) -> Dict[DeductionType, int]:
        """
        Find keyword matches for deduction types.
        
        Args:
            merchant_lower: Lowercase merchant name
            item_descriptions: List of item descriptions
            
        Returns:
            Dictionary mapping deduction types to match counts
        """
        matches = {}
        
        for deduction_type, keywords in cls.DEDUCTION_KEYWORDS.items():
            count = 0
            
            # Check merchant
            for keyword in keywords:
                if keyword in merchant_lower:
                    count += 1
            
            # Check items
            for item in item_descriptions:
                item_lower = item.lower()
                for keyword in keywords:
                    if keyword in item_lower:
                        count += 1
            
            if count > 0:
                matches[deduction_type] = count
        
        return matches
