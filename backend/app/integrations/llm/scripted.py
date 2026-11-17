import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.integrations.llm.base import BaseLLM, LLMReply

Step = (
    LLMReply | Callable[[list[dict[str, Any]]], LLMReply | Awaitable[LLMReply]]
)


@dataclass
class ScriptedLLM(BaseLLM):
    """Модель, которая отвечает заранее заданными шагами.

    Шаг — готовый LLMReply или функция (в том числе async) от истории.
    Нужна для тестов конвейера бота: инструменты, лимиты и отправка
    проверяются по-настоящему, меняется только источник текста.
    """

    steps: list[Step] = field(default_factory=list)
    requests: list[list[dict[str, Any]]] = field(default_factory=list)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMReply:
        self.requests.append([dict(m) for m in messages])
        if not self.steps:
            return LLMReply(content='', tokens=0)
        step = self.steps.pop(0)
        if not callable(step):
            return step
        result = step(messages)
        return await result if inspect.isawaitable(result) else result
