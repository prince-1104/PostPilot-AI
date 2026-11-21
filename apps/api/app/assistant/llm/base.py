"""LLM provider interface used by LangGraph nodes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

from app.observability.usage import LLMResult

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Provider or structured-output failure (safe message for clients)."""

    def __init__(self, message: str, *, code: str = "llm_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class LLMProvider(ABC):
    @abstractmethod
    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
    ) -> LLMResult[T]:
        """Return validated data plus usage metadata. Never returns secrets."""
