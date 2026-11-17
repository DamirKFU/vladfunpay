from datetime import datetime, timedelta, timezone

from app.integrations.funpay.orders import order_from_export
from app.integrations.steam.base import friend_limit
from app.integrations.steam.links import parse_steam_link
from app.integrations.steam.web import parse_pending_page
from app.models.domain import FriendTier, Relationship, SteamFriend
from app.repositories.base import BaseOrderRepository
from app.usecases.friends import FriendsService
from app.usecases.friends_ranking import BuyerInfo, rank_friends

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def sid(n: int) -> str:
    return str(76561198000000000 + n)


def friend(n, days_ago=100, level=None, rel=Relationship.FRIEND):
    return SteamFriend(
        steam_id=sid(n),
        relationship=rel,
        level=level,
        friend_since=NOW - timedelta(days=days_ago),
    )


def test_parse_steam_links():
    trade = parse_steam_link(
        'вот https://steamcommunity.com/tradeoffer/new/?partner=889002523'
        '&token=cc7RC3KB спасибо',
    )
    assert trade.steam_id == '76561198849268251'
    assert trade.trade_token == 'cc7RC3KB'
    profile = parse_steam_link(
        'https://steamcommunity.com/profiles/76561199251723321/',
    )
    assert profile.steam_id == '76561199251723321'
    assert parse_steam_link('steamcommunity.com/id/gaben') is None
    assert (
        parse_steam_link(
            'https://steamcommunity.com/id/gaben',
        ).vanity
        == 'gaben'
    )
    assert parse_steam_link('https://example.com') is None


def test_friend_limit():
    assert friend_limit(None) is None
    assert friend_limit(10) == 300
    assert friend_limit(1000) == 2000


def test_ranking_order_and_candidates():
    friends = [
        friend(1),  # защищён
        friend(2),  # открытый заказ
        friend(3, days_ago=200),  # давний покупатель
        friend(4, days_ago=5),  # свежий покупатель
        friend(5, level=50),  # друг, высокий уровень
        friend(6, level=1),  # друг, низкий уровень
        friend(7, days_ago=1, rel=Relationship.INVITE_SENT),
        friend(8, days_ago=30, rel=Relationship.INVITE_SENT),
        friend(9, rel=Relationship.INVITE_RECEIVED),
    ]
    buyers = {
        sid(2): BuyerInfo('b2', 1, NOW, has_open_order=True),
        sid(3): BuyerInfo('b3', 2, NOW - timedelta(days=60), False),
        sid(4): BuyerInfo('b4', 1, NOW - timedelta(days=3), False),
    }
    # Лимит при уровне 0 — 250; занято 8, держим 245 свободными -> 3 лишних.
    report = rank_friends(
        friends,
        {sid(1)},
        buyers,
        NOW,
        30,
        own_level=0,
        keep_free=245,
    )
    tiers = [r.tier for r in report.ranked]
    assert tiers[:6] == [
        FriendTier.PROTECTED,
        FriendTier.OPEN_ORDER,
        FriendTier.LONG_BUYER,
        FriendTier.BUYER,
        FriendTier.FRIEND,
        FriendTier.FRIEND,
    ]
    assert report.ranked[4].friend.level == 50
    assert report.used == 8  # входящая заявка слот не занимает
    assert report.to_free == 3
    # Первыми уходят старая исходящая заявка, новая заявка, слабый друг.
    assert [c.friend.steam_id for c in report.candidates] == [
        sid(8),
        sid(7),
        sid(6),
    ]
    assert not any(not c.removable for c in report.candidates)


def test_never_removes_protected_even_when_full():
    friends = [friend(1), friend(2)]
    buyers = {sid(2): BuyerInfo('b', 1, NOW, has_open_order=True)}
    report = rank_friends(friends, {sid(1)}, buyers, NOW, 30, 0, 250)
    assert report.to_free == 2
    assert report.candidates == []


def test_parse_pending_page():
    html = """
    <div id="search_results_sentinvites">
      <div class="invite_row" data-steamid="76561198000000001">
        <span class="invite_block_name"><a>Sent One</a></span></div>
    </div>
    <div id="search_results">
      <div class="invite_row" data-steamid="76561198000000002"></div>
    </div>"""
    items = {f.steam_id: f for f in parse_pending_page(html)}
    assert items['76561198000000001'].relationship == 'invite_sent'
    assert items['76561198000000001'].name == 'Sent One'
    assert items['76561198000000002'].relationship == 'invite_received'


async def test_refresh_caches_levels_and_remove_guards(
    container,
    integrations,
    settings_service,
    export_records,
):
    settings = await settings_service.get()
    settings.steam.api_key, settings.steam.steam_id = 'key', sid(0)
    await settings_service.save(settings)
    await container.resolve(FriendsService).protect(sid(1), 'брат')
    # Покупатель с открытым заказом: steam id из ссылки в выгрузке.
    open_order = order_from_export(export_records[2])
    await container.resolve(BaseOrderRepository).upsert_many([open_order])

    gateway = integrations.steam_gateway
    gateway.friend_list = [
        friend(1),
        friend(5, level=None),
        SteamFriend(
            open_order.steam_id, Relationship.FRIEND, friend_since=NOW
        ),
    ]
    gateway.level_map = {sid(0): 20, sid(1): 5, sid(5): 7}
    service = container.resolve(FriendsService)

    report = await service.refresh()
    assert report.own_level == 20
    assert report.limit == 350
    calls = gateway.level_calls
    await service.refresh()
    assert gateway.level_calls == calls  # уровни из кэша

    result = await service.remove([sid(1), open_order.steam_id, sid(5)])
    assert 'защищённом' in result[0]['error']
    assert 'открытый заказ' in result[1]['error']
    assert result[2] == {'steam_id': sid(5), 'removed': True}
    assert gateway.removed == [sid(5)]


def test_steam_api(auth_client, integrations):
    resp = auth_client.post(
        '/api/steam/protected',
        json={'steam_id': sid(1), 'note': 'друг детства'},
    )
    assert resp.status_code == 200
    settings = auth_client.get('/api/settings').json()
    assert settings['friends']['protected'] == [
        {'steam_id': sid(1), 'note': 'друг детства'},
    ]
    report = auth_client.get('/api/steam/friends').json()
    assert report['ranked'] == []
