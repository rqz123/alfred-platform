"""
Classification rules and logic for expense categorization.
"""

from models.schema import ExpenseCategory
from typing import Dict, List
import re


class ClassificationEngine:
    """Handles expense classification and category refinement."""
    
    # Keyword-based category mappings
    CATEGORY_KEYWORDS = {
        ExpenseCategory.FOOD: [
            'grocery', 'supermarket', 'food', 'bakery', 'market', 'deli',
            'bread', 'milk', 'produce', 'fruit', 'vegetable', 'meat'
        ],
        ExpenseCategory.RESTAURANT: [
            'restaurant', 'cafe', 'coffee', 'pizza', 'burger', 'chicken',
            'mexican', 'chinese', 'thai', 'sushi', 'bar', 'alcohol',
            'wine', 'beer', 'liquor', 'takeout', 'delivery', 'bistro'
        ],
        ExpenseCategory.TOOLS: [
            'hardware', 'tool', 'depot', 'equipment', 'supply',
            'wrench', 'hammer', 'drill', 'saw', 'screwdriver'
        ],
        ExpenseCategory.MAINTENANCE: [
            'repair', 'service', 'maintenance', 'mechanic', 'auto',
            'car wash', 'oil change', 'tire', 'garage', 'fix',
            'plumbing', 'electric', 'hvac', 'appliance'
        ],
        ExpenseCategory.UTILITIES: [
            'electric', 'gas', 'water', 'utility', 'power',
            'internet', 'phone', 'cable', 'wireless', 'bill'
        ],
        ExpenseCategory.HEALTHCARE: [
            'pharmacy', 'drug', 'medical', 'doctor', 'clinic',
            'hospital', 'dentist', 'optometrist', 'health',
            'medicine', 'prescription', 'cvs', 'walgreens'
        ],
        ExpenseCategory.TRANSPORTATION: [
            'gas station', 'fuel', 'parking', 'toll', 'transit',
            'uber', 'lyft', 'taxi', 'bus', 'train', 'subway'
        ],
        ExpenseCategory.ENTERTAINMENT: [
            'movie', 'theater', 'cinema', 'game', 'bowling',
            'amusement', 'park', 'museum', 'concert', 'show',
            'ticket', 'entertainment', 'hobby', 'toy'
        ],
        ExpenseCategory.CLOTHING: [
            'clothing', 'apparel', 'fashion', 'shoe', 'dress',
            'shirt', 'pants', 'jacket', 'wear', 'boutique'
        ],
        ExpenseCategory.EDUCATION: [
            'school', 'university', 'college', 'education',
            'bookstore', 'tuition', 'course', 'training',
            'learning', 'academy', 'book'
        ]
    }
    
    # Merchant name patterns for specific categories
    MERCHANT_PATTERNS = {
        ExpenseCategory.FOOD: [
            r'.*\b(walmart|target|costco|whole foods|safeway|kroger|trader joe s|aldi)\b.*',
        ],
        ExpenseCategory.RESTAURANT: [
            r'.*\b(mcdonalds|burger king|wendys|taco bell|subway)\b.*',
            r'.*\b(starbucks|dunkin|peets)\b.*'
        ],
        ExpenseCategory.TOOLS: [
            r'.*\b(home depot|lowes|ace hardware|harbor freight)\b.*'
        ],
        ExpenseCategory.HEALTHCARE: [
            r'.*\b(cvs|walgreens|rite aid)\b.*'
        ],
        ExpenseCategory.TRANSPORTATION: [
            r'.*\b(shell|chevron|exxon|bp|mobil|76|arco)\b.*'
        ]
    }

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Normalize free-form text for regex and keyword matching."""
        return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()
    
    @classmethod
    def classify_by_merchant(cls, merchant_name: str) -> ExpenseCategory:
        """
        Classify expense based on merchant name.
        
        Args:
            merchant_name: Name of the merchant
            
        Returns:
            Best matching ExpenseCategory
        """
        merchant_normalized = cls._normalize_text(merchant_name)
        
        # Check regex patterns first
        for category, patterns in cls.MERCHANT_PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, merchant_normalized):
                    return category
        
        # Check keyword matches
        best_category = ExpenseCategory.OTHER
        max_matches = 0
        
        for category, keywords in cls.CATEGORY_KEYWORDS.items():
            matches = sum(1 for keyword in keywords if keyword in merchant_normalized)
            if matches > max_matches:
                max_matches = matches
                best_category = category
        
        return best_category
    
    @classmethod
    def classify_by_items(cls, item_descriptions: List[str]) -> ExpenseCategory:
        """
        Classify expense based on item descriptions.
        
        Args:
            item_descriptions: List of item descriptions
            
        Returns:
            Best matching ExpenseCategory
        """
        if not item_descriptions:
            return ExpenseCategory.OTHER
        
        # Aggregate keyword matches across all items
        category_scores = {category: 0 for category in ExpenseCategory}
        
        for description in item_descriptions:
            desc_lower = description.lower()
            for category, keywords in cls.CATEGORY_KEYWORDS.items():
                for keyword in keywords:
                    if keyword in desc_lower:
                        category_scores[category] += 1
        
        # Return category with highest score
        best_category = max(category_scores, key=category_scores.get)
        
        if category_scores[best_category] == 0:
            return ExpenseCategory.OTHER
        
        return best_category
    
    @classmethod
    def refine_classification(
        cls,
        ai_suggestion: ExpenseCategory,
        merchant_name: str,
        item_descriptions: List[str] = None,
        use_merchant_override: bool = True,
        use_items_override: bool = True
    ) -> ExpenseCategory:
        """
        Refine AI-suggested classification with rule-based logic.
        
        Args:
            ai_suggestion: Category suggested by AI
            merchant_name: Merchant name
            item_descriptions: Optional item descriptions
            use_merchant_override: Whether to allow merchant-based override
            use_items_override: Whether to allow items-based override
            
        Returns:
            Final ExpenseCategory
        """
        # Start with AI suggestion
        final_category = ai_suggestion
        
        # Override with merchant if confident match
        if use_merchant_override:
            merchant_category = cls.classify_by_merchant(merchant_name)
            if merchant_category != ExpenseCategory.OTHER:
                # Merchant classification takes precedence for strong matches
                merchant_normalized = cls._normalize_text(merchant_name)
                for category, patterns in cls.MERCHANT_PATTERNS.items():
                    for pattern in patterns:
                        if re.match(pattern, merchant_normalized):
                            return category
        
        # Override with items if available and confident
        if use_items_override and item_descriptions:
            items_category = cls.classify_by_items(item_descriptions)
            if items_category != ExpenseCategory.OTHER:
                final_category = items_category
        
        return final_category
