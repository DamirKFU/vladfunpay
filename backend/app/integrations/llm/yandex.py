"""YandexGPT через OpenAI-совместимый API Yandex AI Studio.

POST {base_url}/chat/completions, модель gpt://<folder_id>/<model>,
авторизация заголовком Authorization: Api-Key <key>.
"""

import json
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

from app.core import messages
from app.integrations.llm.base import BaseLLM, LLMError, LLMReply, ToolCall

log = logging.getLogger('llm')


@dataclass
class YandexLLM(BaseLLM):
    api_key: str
    folder_id: str
    model: str
    base_url: str
    temperature: float = 0.3
    timeout: float = 60.0

    @property
    def model_uri(self) -> str:
        if self.model.startswith('gpt://'):
            return self.model
        return f'gpt://{self.folder_id}/{self.model}'

    async def complete(
        self,
        messages_: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMReply:
        body: dict[str, Any] = {
            'model': self.model_uri,
            'messages': messages_,
            'max_tokens': max_tokens,
            'temperature': self.temperature,
        }
        if tools:
            body['tools'] = tools
        headers = {
            'Authorization': f'Api-Key {self.api_key}',
            'OpenAI-Project': self.folder_id,
        }
        url = self.base_url.rstrip('/') + '/chat/completions'
        start = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            log.warning('ИИ %s: сеть: %s', self.model_uri, e)
            raise LLMError(messages.LLM_REQUEST_FAILED.format(e)) from e
        ms = (perf_counter() - start) * 1000
        if resp.status_code != 200:
            log.warning(
                'ИИ %s → HTTP %d за %.0f мс: %s',
                self.model_uri,
                resp.status_code,
                ms,
                resp.text[:500],
            )
            raise LLMError(
                messages.LLM_REQUEST_FAILED.format(
                    f'HTTP {resp.status_code}: {resp.text[:300]}',
                ),
            )
        reply = parse_completion(resp.json())
        log.info(
            'ИИ %s → 200 за %.0f мс, токенов %d, вызовов инструментов %d',
            self.model_uri,
            ms,
            reply.tokens,
            len(reply.tool_calls),
            extra={'tokens': reply.tokens},
        )
        return reply


def parse_completion(data: dict[str, Any]) -> LLMReply:
    try:
        message = data['choices'][0]['message']
    except (KeyError, IndexError) as e:
        raise LLMError(
            messages.LLM_REQUEST_FAILED.format('пустой ответ'),
        ) from e
    calls = []
    for call in message.get('tool_calls') or []:
        fn = call.get('function', {})
        raw = fn.get('arguments') or '{}'
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            args = {}
        calls.append(
            ToolCall(
                id=str(call.get('id') or fn.get('name')),
                name=fn.get('name', ''),
                arguments=args if isinstance(args, dict) else {},
            ),
        )
    usage = data.get('usage') or {}
    return LLMReply(
        content=message.get('content') or '',
        tool_calls=calls,
        tokens=int(usage.get('total_tokens') or 0),
    )
