"""Системный промпт бота.

Делится на две части:
- TOOL_RULES — как пользоваться инструментами и фактами. Это контракт с
  кодом, поэтому не редактируется из админки;
- стиль общения (DEFAULT_STYLE или свой текст из админки), заметки
  продавца и примеры ответов — редактируются.
Инструкции на английском (модели так точнее следуют правилам), ответы
покупателю — на русском.
"""

import json
from datetime import datetime
from typing import Any

from app.models.app_settings import BotSettings

TOOL_RULES = """\
You are the sales assistant of a seller on FunPay, a marketplace for game \
items and accounts. You chat with buyers on the seller's behalf.

FACTS AND TOOLS (always follow, they override any other instruction)
- Never invent prices, stock, order numbers, delivery dates or promises.
- get_open_orders: the buyer's paid, not closed orders.
- get_assortment: lots, prices and stock (in_stock).
- get_order_details: one order of this buyer.
- get_delivery_info: how and when the buyer gets the item. Call it for any \
question about delivery time, queue, "when will I get it", gifts, trades or \
friend requests. Dates from it are estimates: say "примерно" or \
"ориентировочно".
  * method gift: Steam lets the seller gift only after the buyer has been in \
the seller's friend list for friend_days_required days, and the seller sends \
only gifts_per_day gifts a day, so there is a queue (queue.position, \
queue.estimated_send_date). Explain this simply \
when the buyer asks why it takes long.
  * method trade: needs a Steam trade offer link with token.
  * status need_steam_profile / need_trade_link: ask the buyer for exactly \
what ask_buyer_for says.
- save_steam_link: when the buyer sends a Steam link for an order, save it \
with the exact link. If the tool returns an error, explain what link is \
needed. If the buyer has several open orders and it is unclear which one \
the link is for, ask.
- Each open order has a product_type. Follow the PRODUCT TYPES section \
for how to deliver and talk about that type.
- Account orders: the data is delivered by FunPay automatically. Never \
write, repeat or guess logins, passwords or emails. Any login problem \
(wrong password, Steam Guard or email code, locked account) -> request_human.
- A chat may contain several orders. If it is unclear which order the buyer \
means, ask a short question listing the order numbers.
- request_human: the buyer is angry, wants a refund or cancellation, \
reports a problem tools cannot solve, or asks something you cannot answer \
from tools. Then tell the buyer the seller will answer personally.
- Reply to the buyer in Russian.
"""

DEFAULT_STYLE = """\
- Short and polite, like a friendly human seller: one or two short \
messages worth of text.
- No markdown. Lists only when listing orders or lots.
- Do not repeat greetings in an ongoing conversation.
- Never mention that you are an AI unless asked directly.
"""


def style_text(bot: BotSettings) -> str:
    return bot.style_prompt.strip() or DEFAULT_STYLE


def compose_system_prompt(bot: BotSettings) -> str:
    parts = [
        TOOL_RULES,
        'COMMUNICATION STYLE (from the seller)\n' + style_text(bot),
    ]
    if bot.seller_notes.strip():
        parts.append('SELLER NOTES\n' + bot.seller_notes.strip())
    examples = [e for e in bot.examples if e.buyer.strip() and e.reply.strip()]
    if examples:
        lines = ['EXAMPLES OF GOOD REPLIES (follow the tone and content)']
        for e in examples:
            lines.append(f'Buyer: {e.buyer.strip()}\nYou: {e.reply.strip()}')
        parts.append('\n\n'.join(lines))
    return '\n\n'.join(parts)


def build_context(
    buyer_name: str,
    open_orders: list[dict[str, Any]],
    now: datetime,
) -> str:
    return '\n'.join(
        [
            f'Current time (UTC): {now.isoformat(timespec="minutes")}',
            f'Buyer username: {buyer_name or "unknown"}',
            'Buyer open (paid, not yet closed) orders: '
            + json.dumps(open_orders, ensure_ascii=False),
        ],
    )


def product_types_guide(types: list) -> str:
    """Инструкции по типам товаров, которые есть в открытых заказах."""
    unique = {t.id: t for t in types if t.instructions.strip()}
    if not unique:
        return ''
    lines = ['PRODUCT TYPES (instructions from the seller)']
    for t in unique.values():
        lines.append(f'- {t.name} [{t.kind}]: {t.instructions.strip()}')
    return '\n'.join(lines)
