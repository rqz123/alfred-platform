"""
AI provider factory and management.
"""

import os
from services.ai.receipt_ai_provider import ReceiptAIProvider
from services.ai.providers.gemini_provider import GeminiProvider
from services.ai.providers.openai_provider import OpenAIProvider


def get_ai_provider() -> ReceiptAIProvider:
    """
    Get configured AI provider instance.
    
    Returns:
        Initialized AI provider based on environment configuration
        
    Raises:
        ValueError: If provider is not configured or unknown
    """
    provider_name = os.getenv('AI_PROVIDER', '').lower().strip()

    if not provider_name:
        provider_name = 'openai' if os.getenv('OPENAI_API_KEY') else 'gemini'
    
    if provider_name == 'gemini':
        return GeminiProvider()
    elif provider_name == 'openai':
        return OpenAIProvider()
    else:
        raise ValueError(f"Unknown AI provider: {provider_name}")
