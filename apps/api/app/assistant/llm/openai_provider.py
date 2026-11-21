"""OpenAI structured-output adapter."""

from __future__ import annotations

from typing import TypeVar

import structlog
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from app.assistant.llm.base import LLMError, LLMProvider
from app.core.config import Settings

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class OpenAILLMProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not configured.", code="llm_unavailable")
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.ai_request_timeout_seconds,
        )

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
    ) -> T:
        try:
            completion = await self._client.beta.chat.completions.parse(
                model=self._settings.ai_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
            )
        except RateLimitError as exc:
            logger.warning("assistant.llm.rate_limited", provider="openai")
            raise LLMError(
                "The AI provider is rate-limiting requests. Try again shortly.",
                code="llm_rate_limited",
            ) from exc
        except APITimeoutError as exc:
            raise LLMError(
                "The AI provider timed out. Try again shortly.",
                code="llm_timeout",
            ) from exc
        except APIConnectionError as exc:
            raise LLMError(
                "Could not reach the AI provider.",
                code="llm_unavailable",
            ) from exc
        except APIStatusError as exc:
            logger.warning(
                "assistant.llm.provider_status",
                status=exc.status_code,
                provider="openai",
            )
            raise LLMError(
                "The AI provider returned an error.",
                code="llm_error",
            ) from exc

        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            raise LLMError(
                "The AI provider refused to complete this request.",
                code="llm_refusal",
            )
        parsed = message.parsed
        if parsed is None:
            raise LLMError(
                "The AI provider returned an empty structured response.",
                code="llm_invalid_output",
            )
        if isinstance(parsed, schema):
            return parsed
        try:
            return schema.model_validate(parsed)
        except ValidationError as exc:
            raise LLMError(
                "The AI provider returned malformed structured output.",
                code="llm_invalid_output",
            ) from exc
