"""
Abstract interface for AI receipt processing providers.
"""

from abc import ABC, abstractmethod
from typing import List
from models.schema import ReceiptExtractionResult


class ReceiptAIProvider(ABC):
    """Abstract base class for AI receipt extraction providers."""
    
    @abstractmethod
    async def extract_receipt_data(self, image_content: bytes, mime_type: str) -> ReceiptExtractionResult:
        """
        Extract structured data from receipt image.
        
        Args:
            image_content: Binary image content
            mime_type: MIME type of the image
            
        Returns:
            ReceiptExtractionResult: Extracted and structured receipt data
            
        Raises:
            ValueError: If image cannot be processed
            RuntimeError: If API call fails
        """
        pass
    
    @abstractmethod
    def validate_configuration(self) -> bool:
        """
        Validate provider configuration (API keys, etc.).
        
        Returns:
            True if configuration is valid
        """
        pass
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Get provider name.
        
        Returns:
            Provider identifier string
        """
        pass
