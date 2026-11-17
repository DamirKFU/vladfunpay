"""Ответ бота в одном чате: защита от спама и расходов, ИИ, отправка."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.bot.agent import run_agent
from app.bot.catalog import handoff_hit
from app.bot.prompt import (
    build_context,
    compose_system_prompt,
    product_types_guide,
)
from app.bot.templates import find_template, render_reply
from app.bot.tools import ToolContext
from app.core import messages
from app.integrations.funpay.base import BaseMarketplace, IncomingChat
from app.integrations.llm.base import LLMError
from app.integrations.provider import BaseIntegrations, NotConfiguredError
from app.integrations.steam.friendship import (
    BaseFriendshipLookup,
    SandboxFriendshipLookup,
    SnapshotFriendshipLookup,
)
from app.models.app_settings import AppSettings
from app.models.domain import (
    Author,
    BotTrace,
    Channel,
    ChatMessage,
    Conversation,
    OpenOrder,
)
from app.repositories.base import (
    BaseChatRepository,
    BaseOrderRepository,
    BaseSteamLinkRepository,
    BaseUsageRepository,
)
from app.usecases.alerts import OwnerAlerts
from app.usecases.lots import LotCatalogService
from app.usecases.settings import SettingsService

log = logging.getLogger('bot')
MSK = ZoneInfo('Europe/Moscow')

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BotService:
    settings: SettingsService
    chats: BaseChatRepository
    orders: BaseOrderRepository
    links: BaseSteamLinkRepository
    usage: BaseUsageRepository
    integrations: BaseIntegrations
    steam_friendships: SnapshotFriendshipLookup
    sandbox_friendships: SandboxFriendshipLookup
    alerts: OwnerAlerts
    catalog: LotCatalogService
    clock: Clock = utc_now

    def friendships(self, channel: Channel) -> BaseFriendshipLookup:
        if channel == Channel.SANDBOX:
            return self.sandbox_friendships
        return self.steam_friendships

    async def store_incoming(
        self, chat: IncomingChat, channel: Channel
    ) -> bool:
        """Сохраняет новые сообщения. True — есть новое от покупателя."""
        conv = await self.chats.get_conversation(channel, chat.chat_id)
        if conv is None:
            conv = Conversation(
                channel=channel,
                chat_id=chat.chat_id,
                buyer_id=chat.buyer_id,
                buyer_name=chat.buyer_name,
                last_message_at=self.clock(),
            )
        conv.buyer_id = chat.buyer_id or conv.buyer_id
        conv.buyer_name = chat.buyer_name or conv.buyer_name
        conv.last_message_at = self.clock()
        has_buyer = False
        for message in chat.messages:
            await self.chats.add_message(message)
            if message.author == Author.SELLER:
                # Продавец ответил сам — считаем всё до этого отвеченным.
                conv.last_answered_id = max(
                    conv.last_answered_id,
                    message.message_id,
                )
            has_buyer |= message.author == Author.BUYER
        await self.chats.save_conversation(conv)
        return has_buyer

    async def answer(
        self,
        marketplace: BaseMarketplace,
        chat_id: str,
    ) -> BotTrace | None:
        channel = marketplace.channel
        settings = await self.settings.get()
        conv = await self.chats.get_conversation(channel, chat_id)
        if conv is None:
            return None
        history = await self.chats.messages(
            channel,
            chat_id,
            settings.bot.history_messages + 30,
        )
        new = [
            m
            for m in history
            if m.author == Author.BUYER
            and m.message_id > conv.last_answered_id
        ]
        if not new:
            return None
        last_id = max(m.message_id for m in history)
        text = '\n'.join(m.text for m in new)[: settings.bot.max_input_chars]
        trace = BotTrace(
            channel=channel,
            chat_id=chat_id,
            created_at=self.clock(),
            input_text=text,
            reply=None,
            outcome='skipped',
        )
        reply = await self._decide(
            marketplace,
            settings,
            conv,
            history,
            text,
            trace,
        )
        if reply:
            await self._send(marketplace, conv, reply, last_id, trace)
        await self.chats.save_conversation(conv)
        await self.chats.add_trace(trace)
        log.log(
            logging.WARNING if trace.outcome == 'error' else logging.INFO,
            'Бот [%s/%s]: %s %s',
            channel,
            chat_id,
            trace.outcome,
            trace.detail,
            extra={'chat_id': chat_id, 'tokens': trace.tokens},
        )
        return trace

    def _precheck(
        self,
        marketplace: BaseMarketplace,
        settings: AppSettings,
        conv: Conversation,
    ) -> str | None:
        """Причина не отвечать вовсе или None."""
        if marketplace.channel == Channel.FUNPAY and not settings.bot.enabled:
            return 'бот выключен'
        if conv.needs_human:
            return 'чат передан продавцу'
        if self._replies_today(conv) >= settings.bot.chat_daily_replies:
            return 'лимит ответов в чате на сегодня'
        return None

    async def _decide(
        self,
        marketplace: BaseMarketplace,
        settings: AppSettings,
        conv: Conversation,
        history: list[ChatMessage],
        text: str,
        trace: BotTrace,
    ) -> str | None:
        bot = settings.bot
        if reason := self._precheck(marketplace, settings, conv):
            trace.detail = reason
            return None
        channel = marketplace.channel

        async def types_for(orders: list[OpenOrder]) -> dict:
            return await self.catalog.order_types(channel, orders, settings)

        ctx = ToolContext(
            marketplace=marketplace,
            orders=self.orders,
            links=self.links,
            conversation=conv,
            friendships=self.friendships(channel),
            types_for=types_for,
            now=self.clock(),
            resolve_vanity=self._vanity_resolver(settings),
        )
        open_orders = await ctx.open_orders()
        types = await types_for(open_orders)
        reply = await self._handoff_by_type(
            settings,
            conv,
            open_orders,
            types,
            text,
            trace,
        )
        if reply:
            return reply
        if match := find_template(bot, text):
            trace.outcome = 'template'
            trace.detail = f'{match.reason}, совпадение {match.score:.2f}'
            return render_reply(match.template, conv.buyer_name)
        if bot.only_with_open_orders and not open_orders:
            trace.detail = 'нет открытых заказов'
            return None
        return await self._ask_llm(
            settings,
            conv,
            history,
            open_orders,
            types,
            ctx,
            trace,
        )

    async def _handoff_by_type(
        self,
        settings: AppSettings,
        conv: Conversation,
        open_orders: list[OpenOrder],
        types: dict,
        text: str,
        trace: BotTrace,
    ) -> str | None:
        """Например, проблема со входом в купленный аккаунт.

        Сразу владельцу, без ИИ: тут нельзя ошибиться и светить данные.
        """
        for order in open_orders:
            ptype = types[order.order_id]
            word = handoff_hit(ptype, text)
            if not word:
                continue
            conv.needs_human = True
            conv.human_reason = (
                f'{ptype.name}, заказ #{order.order_id}: '
                f'покупатель пишет «{text[:200]}»'
            )
            trace.outcome = 'handoff'
            trace.detail = f'слово «{word}» для типа «{ptype.name}»'
            await self._safe_alert(conv.channel, conv)
            return settings.bot.handoff_reply
        return None

    async def _ask_llm(
        self,
        settings: AppSettings,
        conv: Conversation,
        history: list[ChatMessage],
        open_orders: list[OpenOrder],
        types: dict,
        ctx: ToolContext,
        trace: BotTrace,
    ) -> str | None:
        bot = settings.bot
        day = self._day()
        used = await self.usage.tokens(day)
        if used >= bot.daily_token_limit:
            trace.detail = messages.LLM_DAILY_LIMIT.format(
                used,
                bot.daily_token_limit,
            )
            log.warning(trace.detail)
            return None
        try:
            llm = self.integrations.llm(settings)
            result = await run_agent(
                llm,
                self._prompt(settings, conv, history, open_orders, types),
                ctx,
                bot.max_tokens,
            )
        except (NotConfiguredError, LLMError) as e:
            trace.outcome = 'error'
            trace.detail = str(e)
            return None
        trace.tokens = result.tokens
        trace.tool_calls = result.tool_calls
        await self.usage.add_tokens(day, result.tokens)
        await self._notify_owner(conv.channel, conv, result.tool_calls)
        if not result.reply:
            trace.outcome = 'error'
            trace.detail = 'модель не вернула текст'
            return None
        trace.outcome = 'replied'
        return result.reply

    async def _safe_alert(self, channel: Channel, conv: Conversation) -> None:
        try:
            await self.alerts.handoff(channel, conv)
        except Exception:
            log.exception('Уведомление владельцу упало')

    async def _notify_owner(
        self,
        channel: Channel,
        conv: Conversation,
        calls: list,
    ) -> None:
        """Ошибки инструментов и передача чата — владельцу в Telegram."""
        try:
            await self.alerts.tool_errors(channel, conv, calls)
            if any(c.name == 'request_human' for c in calls):
                await self.alerts.handoff(channel, conv)
        except Exception:  # уведомление не должно ломать ответ покупателю
            log.exception('Уведомление владельцу упало')

    async def _send(
        self,
        marketplace: BaseMarketplace,
        conv: Conversation,
        reply: str,
        last_id: int,
        trace: BotTrace,
    ) -> None:
        latest = await marketplace.last_message_id(conv.chat_id)
        if latest > last_id:
            # Пока думали, покупатель дописал — ответим на всё сразу.
            trace.outcome = 'discarded'
            trace.detail = 'пришло новое сообщение, ответ пересобирается'
            trace.reply = reply
            return
        sent = await marketplace.send(conv.chat_id, reply)
        await self.chats.add_message(sent)
        conv.last_answered_id = max(last_id, sent.message_id)
        day = self._day()
        if conv.replies_day != day:
            conv.replies_day, conv.replies_today = day, 0
        conv.replies_today += 1
        trace.reply = reply

    def _replies_today(self, conv: Conversation) -> int:
        return conv.replies_today if conv.replies_day == self._day() else 0

    def _day(self) -> str:
        return self.clock().astimezone(MSK).date().isoformat()

    def _vanity_resolver(self, settings: AppSettings):  # noqa: ANN202
        if not (settings.steam.api_key and settings.steam.steam_id):
            return None
        return self.integrations.steam(settings).resolve_vanity

    def _prompt(
        self,
        settings: AppSettings,
        conv: Conversation,
        history: list[ChatMessage],
        open_orders: list[OpenOrder],
        types: dict,
    ) -> list[dict]:
        orders = [
            {
                'order_id': o.order_id,
                'title': o.title,
                'price': o.price,
                'product_type': types[o.order_id].name,
                'delivery_method': types[o.order_id].kind,
            }
            for o in open_orders
        ]
        context = build_context(conv.buyer_name, orders, self.clock())
        result = [
            {'role': 'system', 'content': compose_system_prompt(settings.bot)},
            {'role': 'system', 'content': context},
        ]
        guide = product_types_guide(list(types.values()))
        if guide:
            result.append({'role': 'system', 'content': guide})
        recent = history[-settings.bot.history_messages :]
        for m in recent:
            if m.author == Author.BUYER:
                result.append({'role': 'user', 'content': m.text})
            elif m.author in (Author.BOT, Author.SELLER):
                result.append({'role': 'assistant', 'content': m.text})
            elif m.text:
                result.append(
                    {'role': 'system', 'content': f'FunPay notice: {m.text}'},
                )
        return result
