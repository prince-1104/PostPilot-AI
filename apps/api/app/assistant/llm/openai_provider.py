"""OpenAI structured-output adapter with real usage capture."""

from __future__ import annotations

import asyncio
import time
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
from app.observability.usage import LLMResult, LLMUsage

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


def _usage_from_completion(
    completion: object,
    *,
    model: str,
    latency_ms: float,
    success: bool,
    error_category: str | None = None,
) -> LLMUsage:
    usage_obj = getattr(completion, "usage", None)
    req_id = getattr(completion, "id", None)
    if usage_obj is None:
        return LLMUsage(
            provider="openai",
            model=model,
            success=success,
            latency_ms=latency_ms,
            provider_request_id=str(req_id) if req_id else None,
            error_category=error_category,
            usage_known=False,
        )

    input_tokens = getattr(usage_obj, "prompt_tokens", None)
    output_tokens = getattr(usage_obj, "completion_tokens", None)
    total_tokens = getattr(usage_obj, "total_tokens", None)
    cached = None
    details = getattr(usage_obj, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", None)

    known = input_tokens is not None and output_tokens is not None
    return LLMUsage(
        provider="openai",
        model=model,
        success=success,
        latency_ms=latency_ms,
        input_tokens=int(input_tokens) if input_tokens is not None else None,
        output_tokens=int(output_tokens) if output_tokens is not None else None,
        cached_input_tokens=int(cached) if cached is not None else None,
        total_tokens=int(total_tokens) if total_tokens is not None else None,
        provider_request_id=str(req_id) if req_id else None,
        error_category=error_category,
        usage_known=known,
    )


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
    ) -> LLMResult[T]:
        attempts = 1 + max(0, self._settings.ai_llm_max_retries)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await self._parse_once(system=system, user=user, schema=schema)
            except LLMError as exc:
                if exc.code in {"llm_rate_limited", "llm_refusal", "llm_invalid_output"}:
                    raise
                last_error = exc
                if attempt + 1 >= attempts:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))
            except (APITimeoutError, APIConnectionError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    code = "llm_timeout" if isinstance(exc, APITimeoutError) else "llm_unavailable"
                    message = (
                        "The AI provider timed out. Try again shortly."
                        if code == "llm_timeout"
                        else "Could not reach the AI provider."
                    )
                    raise LLMError(message, code=code) from exc
                await asyncio.sleep(0.25 * (attempt + 1))
        raise LLMError("The AI provider failed.", code="llm_error") from last_error

    async def _parse_once(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
    ) -> LLMResult[T]:
        model = self._settings.ai_model
        started = time.perf_counter()
        max_tokens = self._settings.ai_max_output_tokens
        try:
            kwargs: dict = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": schema,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            completion = await self._client.beta.chat.completions.parse(**kwargs)
        except RateLimitError as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "assistant.llm.rate_limited",
                provider="openai",
                latency_ms=round(latency_ms, 1),
            )
            raise LLMError(
                "The AI provider is rate-limiting requests. Try again shortly.",
                code="llm_rate_limited",
            ) from exc
        except APITimeoutError:
            raise
        except APIConnectionError:
            raise
        except APIStatusError as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            body = getattr(exc, "body", None)
            detail = None
            if isinstance(body, dict):
                err = body.get("error")
                if isinstance(err, dict):
                    detail = err.get("message")
            logger.warning(
                "assistant.llm.provider_status",
                status=exc.status_code,
                provider="openai",
                detail=(str(detail)[:180] if detail else None),
                latency_ms=round(latency_ms, 1),
            )
            raise LLMError(
                "The AI provider returned an error.",
                code="llm_error",
            ) from exc

        latency_ms = (time.perf_counter() - started) * 1000
        usage = _usage_from_completion(
            completion, model=model, latency_ms=latency_ms, success=True
        )
        logger.info(
            "assistant.llm.usage",
            provider="openai",
            model=model,
            usage_known=usage.usage_known,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            total_tokens=usage.total_tokens,
            latency_ms=round(latency_ms, 1),
            provider_request_id=usage.provider_request_id,
            schema=schema.__name__,
        )

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
            return LLMResult(data=parsed, usage=usage)
        try:
            return LLMResult(data=schema.model_validate(parsed), usage=usage)
        except ValidationError as exc:
            raise LLMError(
                "The AI provider returned malformed structured output.",
                code="llm_invalid_output",
            ) from exc
