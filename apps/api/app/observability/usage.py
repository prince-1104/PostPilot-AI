"""LLM usage payloads — never invent token counts."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Actual provider-reported usage for one LLM invocation.

    Token fields are None when the provider did not report them (unknown).
    Never coerce missing usage to zero.
    """

    provider: str
    model: str
    success: bool
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    total_tokens: int | None = None
    provider_request_id: str | None = None
    error_category: str | None = None
    usage_known: bool = False
    node_name: str | None = None
    schema_name: str | None = None


@dataclass(frozen=True, slots=True)
class LLMResult[T: BaseModel]:
    data: T
    usage: LLMUsage
