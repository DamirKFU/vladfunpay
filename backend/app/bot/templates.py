"""Шаблоны ответов без ИИ: совпадение по фразе-примеру.

Сообщение покупателя режется на предложения. Предложение похоже на пример,
если в нём есть большая часть слов примера (с грубым стеммингом, чтобы
«получу» и «получить» совпадали) — оценка от 0 до 1. Слова-ключи остались
как запасной вариант.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models.app_settings import BotSettings, ReplyTemplate

_WORD_RE = re.compile(r'[a-zа-я0-9]+')
_SENTENCE_RE = re.compile(r'[.!?\n]+')
STEM_LEN = 5
# Слова, которые почти не несут смысла в вопросах покупателей.
STOP_WORDS = set(
    'а и в во на с со к по за у о же ли не ну то мне я вы ты мой моя мое '
    'мои это там тут уже еще как так да бы подскажите скажите пожалуйста '
    'здравствуйте привет'.split(),
)


def normalize(text: str) -> list[str]:
    text = text.lower().replace('ё', 'е')
    return [
        w[:STEM_LEN] for w in _WORD_RE.findall(text) if w not in STOP_WORDS
    ]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]


def similarity(sentence: str, example: str) -> float:
    """Доля слов примера, найденных в предложении, с поправкой на порядок."""
    words, sample = normalize(sentence), normalize(example)
    if not sample or not words:
        return 0.0
    coverage = len(set(sample) & set(words)) / len(set(sample))
    order = SequenceMatcher(None, sample, words).ratio()
    return round(0.8 * coverage + 0.2 * order, 3)


@dataclass(frozen=True)
class TemplateMatch:
    template: ReplyTemplate
    score: float
    reason: str


def find_template(bot: BotSettings, text: str) -> TemplateMatch | None:
    lowered = text.lower()
    best: TemplateMatch | None = None
    parts = sentences(text) or [text]
    for template in bot.templates:
        if not template.reply.strip():
            continue
        for example in template.examples:
            if not example.strip():
                continue
            score = max(similarity(part, example) for part in parts)
            if score >= bot.template_threshold and (
                best is None or score > best.score
            ):
                best = TemplateMatch(template, score, f'похоже на «{example}»')
        keys = [k.strip().lower() for k in template.keywords if k.strip()]
        hit = next((k for k in keys if k in lowered), None)
        if hit and best is None:
            best = TemplateMatch(template, 1.0, f'слово «{hit}»')
    return best


def render_reply(template: ReplyTemplate, buyer_name: str) -> str:
    return template.reply.replace('{buyer}', buyer_name or '')
