"""
Google Gemini implementation of receipt AI provider.
"""

import os
import google.generativeai as genai
from typing import List
import json
from datetime import datetime
from services.ai.receipt_ai_provider import ReceiptAIProvider
from models.schema import (
    ReceiptExtractionResult, 
    ReceiptItemData, 
    ExpenseCategory,
    DeductionType,
    EvidenceLevel
)


class GeminiProvider(ReceiptAIProvider):
    """Google Gemini AI provider for receipt extraction."""
    
    def __init__(self, api_key: str = None):
        """
        Initialize Gemini provider.
        
        Args:
            api_key: Gemini API key (defaults to env variable)
        """
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not provided")
        
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
    
    def validate_configuration(self) -> bool:
        """Validate Gemini API configuration."""
        return bool(self.api_key)
    
    @property
    def provider_name(self) -> str:
        """Get provider name."""
        return "gemini"
    
    async def extract_receipt_data(
        self, 
        image_content: bytes, 
        mime_type: str
    ) -> ReceiptExtractionResult:
        """
        Extract receipt data using Gemini vision model.
        
        Args:
            image_content: Binary image content
            mime_type: Image MIME type
            
        Returns:
            Structured receipt extraction result
        """
        prompt = self._build_extraction_prompt()
        
        try:
            # Upload image
            image_part = {
                'mime_type': mime_type,
                'data': image_content
            }
            
            # Call Gemini API
            response = self.model.generate_content([prompt, image_part])
            
            # Parse response
            result = self._parse_response(response.text)
            return result
            
        except Exception as e:
            raise RuntimeError(f"Gemini API call failed: {str(e)}")
    
    def _build_extraction_prompt(self) -> str:
        """Build the extraction prompt for Gemini."""
        return """You are an expert at extracting structured data from receipt images.

Analyze this receipt image and extract the following information in JSON format:

{
  "merchant_name": "Full name of the merchant/store",
  "purchase_date": "Date in YYYY-MM-DD format",
  "total_amount": (total amount as number),
  "currency": "USD or other currency code",
  "items": [
    {
      "description": "Item name/description",
      "quantity": (quantity as number, default 1.0),
      "unit_price": (price per unit as number, null if not available),
      "total_price": (total for this item as number),
            "category": "food|restaurant|tools|maintenance|utilities|healthcare|transportation|entertainment|clothing|education|other"
    }
  ],
  "confidence_score": (0.0 to 1.0 - how confident are you in this extraction),
    "category_suggestion": "food|restaurant|tools|maintenance|utilities|healthcare|transportation|entertainment|clothing|education|other",
  "tax_deductible": (true/false - is this potentially tax deductible),
  "deduction_type": "home_office|medical|business|charitable|education|none",
  "deduction_evidence": "Brief explanation why this might be deductible",
  "evidence_level": "high|medium|low|none"
}

IMPORTANT RULES:
1. Extract dates in YYYY-MM-DD format. If only month/day visible, use current year.
2. Parse amounts as numbers without currency symbols.
3. Categorize items based on their purpose (bread->food, wrench->tools, oil change->maintenance).
4. For tax deductibility, consider: medical expenses, home office supplies, business expenses, charitable donations, education costs.
5. Set confidence_score based on image quality and text clarity.
6. If items are not itemized, return empty array for items but still extract total.
7. Return ONLY valid JSON, no additional text or markdown.

JSON:"""
    
    def _parse_response(self, response_text: str) -> ReceiptExtractionResult:
        """
        Parse Gemini response into structured result.
        
        Args:
            response_text: Raw text response from Gemini
            
        Returns:
            Validated ReceiptExtractionResult
        """
        try:
            # Clean response - remove markdown code blocks if present
            clean_text = response_text.strip()
            if clean_text.startswith('```json'):
                clean_text = clean_text[7:]
            if clean_text.startswith('```'):
                clean_text = clean_text[3:]
            if clean_text.endswith('```'):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()
            
            # Parse JSON
            data = json.loads(clean_text)
            
            # Validate and convert
            items = [
                ReceiptItemData(
                    description=item['description'],
                    quantity=item.get('quantity', 1.0),
                    unit_price=item.get('unit_price'),
                    total_price=item['total_price'],
                    category=ExpenseCategory(item.get('category', 'other'))
                )
                for item in data.get('items', [])
            ]
            
            result = ReceiptExtractionResult(
                merchant_name=data['merchant_name'],
                purchase_date=datetime.fromisoformat(data['purchase_date']),
                total_amount=float(data['total_amount']),
                currency=data.get('currency', 'USD'),
                items=items,
                confidence_score=float(data.get('confidence_score', 0.5)),
                category_suggestion=ExpenseCategory(data.get('category_suggestion', 'other')),
                tax_deductible=bool(data.get('tax_deductible', False)),
                deduction_type=DeductionType(data.get('deduction_type', 'none')),
                deduction_evidence=data.get('deduction_evidence', ''),
                evidence_level=EvidenceLevel(data.get('evidence_level', 'none'))
            )
            
            return result
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse Gemini response as JSON: {str(e)}")
        except KeyError as e:
            raise ValueError(f"Missing required field in Gemini response: {str(e)}")
        except Exception as e:
            raise ValueError(f"Failed to validate extraction result: {str(e)}")
