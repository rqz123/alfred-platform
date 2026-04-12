"""
OpenAI implementation of the receipt AI provider.
"""

import asyncio
import base64
import json
import os
from datetime import datetime

from openai import OpenAI

from services.ai.receipt_ai_provider import ReceiptAIProvider
from models.schema import (
    DeductionType,
    EvidenceLevel,
    ExpenseCategory,
    ReceiptExtractionResult,
    ReceiptItemData,
)


class OpenAIProvider(ReceiptAIProvider):
    """OpenAI vision provider for receipt extraction."""
    
    def __init__(self, api_key: str = None):
        """
        Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key (defaults to env variable)
        """
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not provided")
        self.model = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
        self.client = OpenAI(api_key=self.api_key)
    
    def validate_configuration(self) -> bool:
        """Validate OpenAI API configuration."""
        return bool(self.api_key)
    
    @property
    def provider_name(self) -> str:
        """Get provider name."""
        return "openai"
    
    async def extract_receipt_data(
        self, 
        image_content: bytes, 
        mime_type: str
    ) -> ReceiptExtractionResult:
        """
        Extract receipt data using an OpenAI vision-capable model.
        
        Args:
            image_content: Binary image content
            mime_type: Image MIME type
            
        Returns:
            Structured receipt extraction result
        """
        return await asyncio.to_thread(
            self._extract_receipt_data_sync,
            image_content,
            mime_type,
        )

    def _extract_receipt_data_sync(
        self,
        image_content: bytes,
        mime_type: str,
    ) -> ReceiptExtractionResult:
        """Execute the OpenAI request synchronously."""
        prompt = self._build_extraction_prompt()
        image_base64 = base64.b64encode(image_content).decode('utf-8')

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You extract structured data from receipt images. "
                            "Always return a valid JSON object only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_base64}"
                                },
                            },
                        ],
                    },
                ],
            )
        except Exception as exc:
            raise RuntimeError(f"OpenAI API call failed: {exc}") from exc

        content = response.choices[0].message.content
        if not content:
            raise ValueError("OpenAI returned an empty response")

        return self._parse_response(content)

    def _build_extraction_prompt(self) -> str:
        """Build the extraction prompt for OpenAI."""
        return """Analyze this receipt image and extract the following information in JSON format:

{
  "merchant_name": "Full name of the merchant/store",
  "purchase_date": "Date in YYYY-MM-DD format",
  "total_amount": 0.0,
  "currency": "USD or other currency code",
  "items": [
    {
      "description": "Item name or description",
      "quantity": 1.0,
      "unit_price": null,
      "total_price": 0.0,
            "category": "food|restaurant|tools|maintenance|utilities|healthcare|transportation|entertainment|clothing|education|other"
    }
  ],
  "confidence_score": 0.0,
    "category_suggestion": "food|restaurant|tools|maintenance|utilities|healthcare|transportation|entertainment|clothing|education|other",
  "tax_deductible": false,
  "deduction_type": "home_office|medical|business|charitable|education|none",
  "deduction_evidence": "Short explanation for deduction eligibility",
  "evidence_level": "high|medium|low|none"
}

Rules:
1. Return valid JSON only.
2. Use YYYY-MM-DD for dates. If the year is missing, infer the current year.
3. Parse money as numbers without symbols.
4. If line items are not readable, return an empty array.
5. Classify items by usage, not just merchant type.
6. Be conservative about tax deductibility and confidence.
7. Use category and deduction enums exactly as specified.
"""

    def _parse_response(self, response_text: str) -> ReceiptExtractionResult:
        """Parse the OpenAI JSON response into a validated result."""
        try:
            clean_text = response_text.strip()
            if clean_text.startswith('```json'):
                clean_text = clean_text[7:]
            if clean_text.startswith('```'):
                clean_text = clean_text[3:]
            if clean_text.endswith('```'):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()

            data = json.loads(clean_text)

            items = [
                ReceiptItemData(
                    description=item['description'],
                    quantity=item.get('quantity', 1.0),
                    unit_price=item.get('unit_price'),
                    total_price=item['total_price'],
                    category=ExpenseCategory(item.get('category', 'other')),
                )
                for item in data.get('items', [])
            ]

            return ReceiptExtractionResult(
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
                evidence_level=EvidenceLevel(data.get('evidence_level', 'none')),
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse OpenAI response as JSON: {exc}") from exc
        except KeyError as exc:
            raise ValueError(f"Missing required field in OpenAI response: {exc}") from exc
        except Exception as exc:
            raise ValueError(f"Failed to validate OpenAI extraction result: {exc}") from exc
