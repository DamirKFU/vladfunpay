from datetime import datetime, timedelta, timezone

from app.integrations.funpay.orders import order_from_export
from app.integrations.steam.base import friend_limit
from app.integrations.steam.links import parse_steam_link
from app.integrations.steam.web import parse_pending_page
from app.models.domain import Relationship, SteamFriend
from app.repositories.base import BaseOrderRepository
from app.usecases.friends import FriendsService
from app.usecases.friends_ranking import BuyerInfo, rank_friends

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def sid(n: int) -> str:
    return str(76561198000000000 + n)


def friend(n, days_ago=100, rel=Relationship.FRIEND):
    return SteamFriend(
        steam_id=sid(n),
        relationship=rel,
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


async def test_refresh_loads_only_own_level(
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
        friend(5),
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
    assert calls == 1
    await service.refresh()
    assert gateway.level_calls == calls  # уровни из кэша


def test_steam_api(auth_client, caplog):
    caplog.set_level('INFO', logger='steam.friends')
    resp = auth_client.post(
        '/api/steam/protected',
        json={'steam_id': sid(1), 'note': 'друг детства'},
    )
    assert resp.status_code == 200
    settings = auth_client.get('/api/settings').json()
    assert settings['friends']['protected'] == [
        {'steam_id': sid(1), 'note': 'друг детства'},
    ]
    assert f'защита {sid(1)} включена' in caplog.text
    report = auth_client.get('/api/steam/friends').json()
    assert report['ranked'] == []
    removed = auth_client.post(
        '/api/steam/friends/remove',
        json={'steam_ids': [sid(2)]},
    )
    assert removed.status_code == 404
    assert (
        auth_client.delete(f'/api/steam/protected/{sid(1)}').status_code == 200
    )
    assert f'защита {sid(1)} снята' in caplog.text


def test_rank_prefers_recent_purchases_then_recent_friendships():
    friends = [
        friend(1, days_ago=300),
        friend(2, days_ago=400),
        friend(3, days_ago=2),
        friend(4, days_ago=3),
        friend(5, days_ago=1, rel=Relationship.INVITE_SENT),
        friend(6, rel=Relationship.INVITE_RECEIVED),
        friend(7),
        friend(8),
        friend(9, days_ago=1),
    ]
    buyers = {
        sid(1): BuyerInfo('recent', 1, NOW, False),
        sid(2): BuyerInfo('past', 1, NOW - timedelta(days=60), False),
        sid(7): BuyerInfo('open', 1, NOW, True),
        sid(9): BuyerInfo(
            'old purchase, new friend', 1, NOW - timedelta(days=60), False
        ),
    }
    report = rank_friends(friends, {sid(5), sid(8)}, buyers, own_level=0)
    assert [r.friend.steam_id for r in report.ranked] == [
        sid(8),
        sid(7),
        sid(1),
        sid(9),
        sid(2),
        sid(3),
        sid(4),
        sid(5),
        sid(6),
    ]
    assert report.used == 8
