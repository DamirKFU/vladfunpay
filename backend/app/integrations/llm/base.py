from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens: int = 0


class BaseLLM(ABC):
    """Чат-модель с вызовом функций в формате OpenAI Chat Completions."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMReply: ...
