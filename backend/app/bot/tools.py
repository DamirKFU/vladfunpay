"""Инструменты, которые ИИ вызывает во время ответа покупателю.

Модель только просит действие, а проверку и запись делает код: чужой
заказ, кривую ссылку или несуществующий лот модель «протолкнуть» не может.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.bot.delivery import plan_delivery, schedule_gifts
from app.core import messages
from app.integrations.funpay.base import BaseMarketplace
from app.integrations.steam.friendship import BaseFriendshipLookup
from app.integrations.steam.links import SteamLink, parse_steam_link
from app.models.app_settings import ProductKind, ProductType
from app.models.domain import Conversation, OpenOrder, SteamLinkRecord
from app.repositories.base import BaseOrderRepository, BaseSteamLinkRepository

log = logging.getLogger('bot.tools')
VanityResolver = Callable[[str], Awaitable[str | None]]
TypesResolver = Callable[
    [list[OpenOrder]],
    Awaitable[dict[str, ProductType]],
]
ASSORTMENT_LIMIT = 30


@dataclass
class ToolContext:
    marketplace: BaseMarketplace
    orders: BaseOrderRepository
    links: BaseSteamLinkRepository
    conversation: Conversation
    friendships: BaseFriendshipLookup
    types_for: TypesResolver
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolve_vanity: VanityResolver | None = None
    _open_orders: list[OpenOrder] | None = field(default=None, init=False)

    async def open_orders(self) -> list[OpenOrder]:
        if self._open_orders is None:
            self._open_orders = await self.marketplace.open_orders(
                self.conversation.buyer_id,
            )
        return self._open_orders

    async def link_for(self, order_id: str) -> SteamLink | None:
        """Ссылка Steam по заказу: из чата (бот) или из выгрузки FunPay."""
        for record in await self.links.list(self.marketplace.channel):
            if record.order_id == order_id:
                parsed = parse_steam_link(record.link)
                if parsed and record.steam_id and not parsed.steam_id:
                    parsed = SteamLink(
                        url=parsed.url,
                        steam_id=record.steam_id,
                        vanity=parsed.vanity,
                        trade_token=parsed.trade_token,
                    )
                return parsed
        order = await self.orders.get(order_id)
        if order and order.steam_link:
            return parse_steam_link(order.steam_link)
        return None


def _order_dict(o: OpenOrder) -> dict[str, Any]:
    return {'order_id': o.order_id, 'title': o.title, 'price': o.price}


async def get_open_orders(ctx: ToolContext) -> Any:
    return [_order_dict(o) for o in await ctx.open_orders()]


async def get_assortment(ctx: ToolContext, query: str = '') -> Any:
    offers = await ctx.marketplace.offers()
    q = query.strip().lower()
    items = [o for o in offers if not q or q in o.title.lower()]
    return [
        {
            'title': o.title,
            'price': o.price,
            'in_stock': o.amount,
            'auto_delivery': o.auto_delivery,
        }
        for o in items[:ASSORTMENT_LIMIT]
    ]


async def get_order_details(ctx: ToolContext, order_id: str) -> Any:
    order_id = order_id.lstrip('#').strip()
    for o in await ctx.open_orders():
        if o.order_id == order_id:
            return {**_order_dict(o), 'status': 'paid'}
    order = await ctx.orders.get(order_id)
    if order and order.buyer_id == ctx.conversation.buyer_id:
        return {
            'order_id': order.order_uid,
            'title': f'{order.game} · {order.category}',
            'price': order.amount,
            'status': order.status,
        }
    return {'error': messages.ORDER_NOT_FOUND.format(order_id)}


async def save_steam_link(ctx: ToolContext, order_id: str, link: str) -> Any:
    order_id = order_id.lstrip('#').strip()
    order = next(
        (o for o in await ctx.open_orders() if o.order_id == order_id),
        None,
    )
    if order is None:
        return {'error': messages.ORDER_NOT_FOUND.format(order_id)}
    parsed = parse_steam_link(link)
    if parsed is None:
        return {'error': messages.STEAM_LINK_INVALID.format(link)}
    method = (await ctx.types_for([order]))[order.order_id].kind
    if method == ProductKind.ACCOUNT:
        return {
            'error': 'this order is an account delivered by FunPay '
            'automatically, no Steam link is needed',
        }
    if method == ProductKind.TRADE and not parsed.trade_token:
        return {
            'error': 'this order is delivered by trade: a trade offer link '
            'with token is required',
        }
    steam_id = parsed.steam_id
    if steam_id is None and parsed.vanity and ctx.resolve_vanity:
        steam_id = await ctx.resolve_vanity(parsed.vanity)
    if method == ProductKind.GIFT and steam_id is None:
        return {
            'error': 'could not get Steam ID from this link, ask for '
            'https://steamcommunity.com/profiles/<17 digits>',
        }
    await ctx.links.save(
        SteamLinkRecord(
            channel=ctx.marketplace.channel,
            order_id=order_id,
            buyer_id=ctx.conversation.buyer_id,
            buyer_name=ctx.conversation.buyer_name,
            link=parsed.url,
            steam_id=steam_id,
            saved_at=datetime.now(timezone.utc),
        ),
    )
    return {'saved': True, 'order_id': order_id, 'steam_id': steam_id}


async def get_delivery_info(ctx: ToolContext, order_id: str) -> Any:
    order_id = order_id.lstrip('#').strip()
    mine = {o.order_id for o in await ctx.open_orders()}
    if order_id not in mine:
        return {'error': messages.ORDER_NOT_FOUND.format(order_id)}
    # Очередь считаем по всем открытым заказам продавца, не только этого
    # покупателя.
    all_orders = await ctx.marketplace.open_orders(None)
    if not any(o.order_id == order_id for o in all_orders):
        all_orders = [*all_orders, *await ctx.open_orders()]
    types = await ctx.types_for(all_orders)
    plans = []
    for order in all_orders:
        link = await ctx.link_for(order.order_id)
        friendship = await ctx.friendships.get(
            order.buyer_id,
            link.steam_id if link else None,
        )
        plans.append(
            plan_delivery(
                order,
                types[order.order_id],
                link,
                friendship,
                ctx.now,
            ),
        )
    plan = next(p for p in plans if p.order.order_id == order_id)
    info = dict(plan.info)
    queue = schedule_gifts(plans, ctx.now).get(order_id)
    if queue:
        info['queue'] = queue
    return info


async def request_human(ctx: ToolContext, reason: str = '') -> Any:
    ctx.conversation.needs_human = True
    ctx.conversation.human_reason = reason[:300]
    return {'ok': True}


Handler = Callable[..., Awaitable[Any]]

HANDLERS: dict[str, Handler] = {
    'get_open_orders': get_open_orders,
    'get_assortment': get_assortment,
    'get_order_details': get_order_details,
    'save_steam_link': save_steam_link,
    'get_delivery_info': get_delivery_info,
    'request_human': request_human,
}


def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': description,
            'parameters': {
                'type': 'object',
                'properties': props,
                'required': required,
            },
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _fn(
        'get_open_orders',
        "List this buyer's paid orders that are not closed yet.",
        {},
        [],
    ),
    _fn(
        'get_assortment',
        'List seller lots with price and current stock (in_stock). '
        'Optional query filters by title substring.',
        {'query': {'type': 'string', 'description': 'title filter'}},
        [],
    ),
    _fn(
        'get_order_details',
        'Get status and details of one order of this buyer.',
        {'order_id': {'type': 'string'}},
        ['order_id'],
    ),
    _fn(
        'save_steam_link',
        'Save the Steam profile or trade offer link the buyer sent for '
        'an open order. Pass the link exactly as the buyer wrote it.',
        {'order_id': {'type': 'string'}, 'link': {'type': 'string'}},
        ['order_id', 'link'],
    ),
    _fn(
        'get_delivery_info',
        'How and when the buyer gets the item of an open order: delivery '
        'method (gift needs N days of Steam friendship, trade needs a trade '
        'link), what is missing from the buyer, estimated date and the '
        'approximate place in the gift queue. Use it for any question like '
        '"when will I get it".',
        {'order_id': {'type': 'string'}},
        ['order_id'],
    ),
    _fn(
        'request_human',
        'Hand the conversation over to the human seller. The bot stops '
        'replying in this chat until the seller resumes it.',
        {'reason': {'type': 'string'}},
        ['reason'],
    ),
]


async def call_tool(
    ctx: ToolContext,
    name: str,
    arguments: dict[str, Any],
) -> Any:
    handler = HANDLERS.get(name)
    if handler is None:
        result: Any = {'error': f'unknown tool {name}'}
    else:
        try:
            result = await handler(ctx, **arguments)
        except TypeError as e:
            result = {'error': f'bad arguments: {e}'}
        except Exception as e:
            log.exception('Инструмент %s упал', name)
            result = {'error': f'tool failed: {e}'}
    failed = isinstance(result, dict) and 'error' in result
    log.log(
        logging.WARNING if failed else logging.INFO,
        'Инструмент %s(%s) [%s/%s] → %s',
        name,
        json.dumps(arguments, ensure_ascii=False)[:300],
        ctx.marketplace.channel,
        ctx.conversation.chat_id,
        json.dumps(result, ensure_ascii=False, default=str)[:500],
        extra={'chat_id': ctx.conversation.chat_id, 'tool': name},
    )
    return result
