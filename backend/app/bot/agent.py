import json
from dataclasses import dataclass, field
from typing import Any

from app.bot.tools import TOOL_SCHEMAS, ToolContext, call_tool
from app.integrations.llm.base import BaseLLM
from app.models.domain import ToolCallTrace

MAX_ROUNDS = 4


@dataclass
class AgentResult:
    reply: str
    tokens: int = 0
    tool_calls: list[ToolCallTrace] = field(default_factory=list)


async def run_agent(
    llm: BaseLLM,
    messages: list[dict[str, Any]],
    ctx: ToolContext,
    max_tokens: int,
    max_rounds: int = MAX_ROUNDS,
) -> AgentResult:
    """Цикл «модель -> инструменты -> модель», пока не будет текста."""
    result = AgentResult(reply='')
    history = list(messages)
    for _ in range(max_rounds):
        reply = await llm.complete(history, TOOL_SCHEMAS, max_tokens)
        result.tokens += reply.tokens
        if not reply.tool_calls:
            result.reply = reply.content.strip()
            return result
        history.append(
            {
                'role': 'assistant',
                'content': reply.content or '',
                'tool_calls': [
                    {
                        'id': c.id,
                        'type': 'function',
                        'function': {
                            'name': c.name,
                            'arguments': json.dumps(
                                c.arguments,
                                ensure_ascii=False,
                            ),
                        },
                    }
                    for c in reply.tool_calls
                ],
            },
        )
        for call in reply.tool_calls:
            output = await call_tool(ctx, call.name, call.arguments)
            result.tool_calls.append(
                ToolCallTrace(
                    name=call.name,
                    arguments=call.arguments,
                    result=output,
                ),
            )
            history.append(
                {
                    'role': 'tool',
                    'tool_call_id': call.id,
                    'content': json.dumps(output, ensure_ascii=False),
                },
            )
    return result
