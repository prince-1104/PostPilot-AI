"""Build the configured LLM provider."""

from __future__ import annotations

from app.assistant.llm.base import LLMError, LLMProvider
from app.assistant.llm.fake import FakeLLMProvider
from app.assistant.llm.openai_provider import OpenAILLMProvider
from app.core.config import Settings


def build_llm_provider(settings: Settings) -> LLMProvider:
    if not settings.ai_ready:
        raise LLMError(
            "AI assistant is disabled or not configured. Set AI_ENABLED=true and provider "
            "credentials (for example OPENAI_API_KEY) to enable drafting.",
            code="llm_unavailable",
        )
    if settings.ai_provider == "fake":
        return FakeLLMProvider()
    if settings.ai_provider == "openai":
        return OpenAILLMProvider(settings)
    raise LLMError(f"Unsupported AI provider: {settings.ai_provider}", code="llm_unavailable")
