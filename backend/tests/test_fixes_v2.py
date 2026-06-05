# tests/test_fixes_v2.py
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy import select, func, update
from datetime import datetime, timezone

from app.models import User, Monitor, FoundItem, SeenItem
from app.scheduler.tasks import MonitorScheduler, check_monitor, process_pending_notifications
from app.main import clean_startup_reset
from app.scraper.parser import VintedItem

@pytest.mark.asyncio
async def test_duplicate_notification_prevention_same_user(db_session):
    """Ensure that if two monitors find the same item for the same user, only one new finding is queued."""
    user = User(username="dupe_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    m1 = Monitor(user_id=user.id, name="M1", original_url="u1", params_json="{}", domains_json='["vinted.pl"]', last_check_at=datetime.now(timezone.utc), items_found_count=10)
    m2 = Monitor(user_id=user.id, name="M2", original_url="u2", params_json="{}", domains_json='["vinted.pl"]', last_check_at=datetime.now(timezone.utc), items_found_count=10)
    db_session.add_all([m1, m2])
    await db_session.commit()
    await db_session.refresh(m1)
    await db_session.refresh(m2)

    item = VintedItem(id=123, title="Dupe Item", price=10.0, currency="PLN", brand="Nike", size="M", condition="New", photo_url="p", item_url="u", domain="vinted.pl", seller_id=999)

    # Mock VintedClient to return the same item for both monitors
    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[item])
    mock_client.close = AsyncMock()

    # Run check_monitor for M1
    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()):
        await check_monitor(m1.id, scraper_client=mock_client)
        # Run check_monitor for M2
        await check_monitor(m2.id, scraper_client=mock_client)

    seen_result = await db_session.execute(select(SeenItem).where(SeenItem.user_id == user.id, SeenItem.vinted_item_id == 123))
    assert len(seen_result.scalars().all()) == 1

    found_result = await db_session.execute(select(FoundItem).where(FoundItem.vinted_item_id == 123, FoundItem.monitor_id.in_([m1.id, m2.id])))
    found_items = found_result.scalars().all()
    assert len(found_items) == 1
    assert found_items[0].notified is False

@pytest.mark.asyncio
async def test_cross_user_notifications(db_session):
    """Ensure that Item 1 found by User A is still notified to User B."""
    u1 = User(username="user_a", telegram_bot_token="t1", telegram_chat_id="c1")
    u1.set_password("p")
    u2 = User(username="user_b", telegram_bot_token="t2", telegram_chat_id="c2")
    u2.set_password("p")
    db_session.add_all([u1, u2])
    await db_session.commit()
    await db_session.refresh(u1)
    await db_session.refresh(u2)

    m1 = Monitor(user_id=u1.id, name="MA", original_url="ua", params_json="{}", domains_json='["vinted.pl"]', last_check_at=datetime.now(timezone.utc), items_found_count=1)
    m2 = Monitor(user_id=u2.id, name="MB", original_url="ub", params_json="{}", domains_json='["vinted.pl"]', last_check_at=datetime.now(timezone.utc), items_found_count=1)
    db_session.add_all([m1, m2])
    await db_session.commit()

    item = VintedItem(id=456, title="Cross Item", price=10.0, currency="PLN", brand="Nike", size="M", condition="New", photo_url="p", item_url="u", domain="vinted.pl", seller_id=999)

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[item])
    mock_client.close = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()):
        await check_monitor(m1.id, scraper_client=mock_client)
        await check_monitor(m2.id, scraper_client=mock_client)

    # Verify:
    # Both users should have a FoundItem with notified=False
    found_result = await db_session.execute(select(FoundItem).where(FoundItem.vinted_item_id == 456, FoundItem.notified == False))
    assert len(found_result.scalars().all()) == 2


@pytest.mark.asyncio
async def test_cross_domain_duplicate_item_ids_are_processed_per_domain(db_session):
    """Selected domains are processed independently, even when stable item IDs overlap."""
    user = User(username="cross_domain_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name="Cross Domain",
        original_url="https://www.vinted.fr/catalog?search_text=nike",
        params_json="{}",
        domains_json='["vinted.fr", "vinted.de"]',
        last_check_at=datetime.now(timezone.utc),
        items_found_count=0,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    duplicate_fr = VintedItem(
        id=1001,
        title="Duplicate",
        price=10.0,
        currency="EUR",
        brand="Nike",
        size="M",
        condition="New",
        photo_url="p",
        item_url="https://www.vinted.fr/items/1001",
        domain="vinted.fr",
        seller_id=1,
    )
    duplicate_de = VintedItem(
        id=1001,
        title="Duplicate",
        price=10.0,
        currency="EUR",
        brand="Nike",
        size="M",
        condition="New",
        photo_url="p",
        item_url="https://www.vinted.de/items/1001",
        domain="vinted.de",
        seller_id=1,
    )
    unique_de = VintedItem(
        id=1002,
        title="New on DE",
        price=12.0,
        currency="EUR",
        brand="Nike",
        size="M",
        condition="New",
        photo_url="p",
        item_url="https://www.vinted.de/items/1002",
        domain="vinted.de",
        seller_id=2,
    )

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[duplicate_fr, duplicate_de, unique_de])
    mock_client.close = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()):
        await check_monitor(monitor.id, scraper_client=mock_client)

    seen_result = await db_session.execute(
        select(SeenItem).where(SeenItem.user_id == user.id).order_by(SeenItem.vinted_item_id, SeenItem.domain)
    )
    seen_items = seen_result.scalars().all()
    assert [(item.vinted_item_id, item.domain) for item in seen_items] == [
        (1001, "vinted.de"),
        (1001, "vinted.fr"),
        (1002, "vinted.de"),
    ]

    found_result = await db_session.execute(
        select(FoundItem).where(FoundItem.monitor_id == monitor.id).order_by(FoundItem.vinted_item_id, FoundItem.domain)
    )
    found_items = found_result.scalars().all()
    assert [(item.vinted_item_id, item.domain) for item in found_items] == [
        (1001, "vinted.de"),
        (1001, "vinted.fr"),
        (1002, "vinted.de"),
    ]
    assert all(item.notified is False for item in found_items)


@pytest.mark.asyncio
async def test_cold_start_on_restart(db_session):
    """Verify that after clean_startup_reset, the first check creates only baseline seen state."""
    user = User(username="cold_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()

    monitor = Monitor(user_id=user.id, name="Cold M", original_url="u", params_json="{}", domains_json='["vinted.pl"]', last_check_at=datetime.now(timezone.utc), items_found_count=10)
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    # Run cleanup
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    with patch("app.database.AsyncSessionLocal", side_effect=session_factory):
        await clean_startup_reset()

    # Re-fetch monitor
    await db_session.refresh(monitor)
    assert monitor.last_check_at is None
    assert monitor.items_found_count == 0

    # Run check_monitor
    item = VintedItem(id=789, title="Initial Item", price=10.0, currency="PLN", brand="Nike", size="M", condition="New", photo_url="p", item_url="u", domain="vinted.pl", seller_id=999)
    
    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[item])
    mock_client.close = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()):
        await check_monitor(monitor.id, scraper_client=mock_client)

    seen = await db_session.execute(select(SeenItem).where(SeenItem.vinted_item_id == 789))
    assert seen.scalar_one_or_none() is not None

    found = await db_session.execute(select(FoundItem).where(FoundItem.vinted_item_id == 789))
    assert found.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_cold_start_repeat_then_new_item_sends_only_new_notification(db_session):
    user = User(username="cold_sequence_user", telegram_bot_token="runtime-test-token", telegram_chat_id="10001")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name="Cold Sequence",
        original_url="https://www.vinted.fr/catalog?search_text=nike",
        params_json="{}",
        domains_json='["vinted.fr"]',
        last_check_at=None,
        items_found_count=0,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    def make_item(item_id: int) -> VintedItem:
        return VintedItem(
            id=item_id,
            title=f"Item {item_id}",
            price=10.0 + item_id,
            currency="EUR",
            brand="Nike",
            size="M",
            condition="New",
            photo_url="",
            item_url=f"https://www.vinted.fr/items/{item_id}",
            domain="vinted.fr",
            seller_id=item_id,
        )

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(side_effect=[
        [make_item(1), make_item(2), make_item(3)],
        [make_item(1), make_item(2), make_item(3)],
        [make_item(4), make_item(1), make_item(2), make_item(3)],
    ])
    mock_client.close = AsyncMock()
    notify_mock = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", notify_mock):
        await check_monitor(monitor.id, scraper_client=mock_client)

        seen_count = (await db_session.execute(select(func.count(SeenItem.id)).where(SeenItem.user_id == user.id))).scalar_one()
        found_count = (await db_session.execute(select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id))).scalar_one()
        assert seen_count == 3
        assert found_count == 0
        notify_mock.assert_not_called()

        await check_monitor(monitor.id, scraper_client=mock_client)
        found_count = (await db_session.execute(select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id))).scalar_one()
        assert found_count == 0
        notify_mock.assert_not_called()

        await check_monitor(monitor.id, scraper_client=mock_client)

    found_items = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id))).scalars().all()
    assert [item.vinted_item_id for item in found_items] == [4]
    assert found_items[0].notified is False
    notify_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_filter_skips_wrong_brand_item_without_found_item_or_notification(db_session):
    user = User(username="brand_filter_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name="Brand Filter",
        original_url="https://www.vinted.fr/catalog?brand_ids[]=123",
        params_json=json.dumps({"brand_ids[]": [123], "order": "newest_first"}),
        domains_json='["vinted.fr"]',
        last_check_at=datetime.now(timezone.utc),
        items_found_count=0,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    wrong_brand = VintedItem(
        id=8101,
        title="Wrong Brand",
        price=10.0,
        currency="EUR",
        brand="Other",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.fr/items/8101",
        domain="vinted.fr",
        seller_id=1,
        brand_id=999,
    )
    matching_brand = VintedItem(
        id=8102,
        title="Matching Brand",
        price=12.0,
        currency="EUR",
        brand="Target",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.fr/items/8102",
        domain="vinted.fr",
        seller_id=2,
        brand_id=123,
    )

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[wrong_brand, matching_brand])
    mock_client.close = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()) as notify_mock:
        await check_monitor(monitor.id, scraper_client=mock_client)

    found_items = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id))).scalars().all()
    assert [item.vinted_item_id for item in found_items] == [8102]
    seen_items = (await db_session.execute(select(SeenItem).where(SeenItem.user_id == user.id))).scalars().all()
    assert [item.vinted_item_id for item in seen_items] == [8102]
    notify_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_brand_id_does_not_create_found_item_for_brand_monitor(db_session):
    user = User(username="missing_brand_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name="Missing Brand",
        original_url="https://www.vinted.fr/catalog?brand_ids[]=123",
        params_json=json.dumps({"brand_ids[]": [123], "order": "newest_first"}),
        domains_json='["vinted.fr"]',
        last_check_at=datetime.now(timezone.utc),
        items_found_count=0,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    item = VintedItem(
        id=8201,
        title="Missing Brand ID",
        price=10.0,
        currency="EUR",
        brand="",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.fr/items/8201",
        domain="vinted.fr",
        seller_id=1,
        brand_id=None,
    )

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[item])
    mock_client.close = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()) as notify_mock:
        await check_monitor(monitor.id, scraper_client=mock_client)

    found_count = (await db_session.execute(select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id))).scalar_one()
    seen_count = (await db_session.execute(select(func.count(SeenItem.id)).where(SeenItem.user_id == user.id))).scalar_one()
    assert found_count == 0
    assert seen_count == 0
    notify_mock.assert_not_called()


@pytest.mark.asyncio
async def test_cold_start_brand_monitor_seeds_matching_seen_only(db_session):
    user = User(username="cold_brand_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name="Cold Brand",
        original_url="https://www.vinted.fr/catalog?brand_ids[]=123",
        params_json=json.dumps({"brand_ids[]": [123], "order": "newest_first"}),
        domains_json='["vinted.fr"]',
        last_check_at=None,
        items_found_count=0,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    matching = VintedItem(
        id=8301,
        title="Baseline Match",
        price=10.0,
        currency="EUR",
        brand="Target",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.fr/items/8301",
        domain="vinted.fr",
        seller_id=1,
        brand_id=123,
    )
    wrong = VintedItem(
        id=8302,
        title="Baseline Wrong",
        price=10.0,
        currency="EUR",
        brand="Other",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.fr/items/8302",
        domain="vinted.fr",
        seller_id=2,
        brand_id=999,
    )

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(return_value=[matching, wrong])
    mock_client.close = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()) as notify_mock:
        await check_monitor(monitor.id, scraper_client=mock_client)

    seen_items = (await db_session.execute(select(SeenItem).where(SeenItem.user_id == user.id))).scalars().all()
    assert [item.vinted_item_id for item in seen_items] == [8301]
    found_count = (await db_session.execute(select(func.count(FoundItem.id)).where(FoundItem.monitor_id == monitor.id))).scalar_one()
    assert found_count == 0
    notify_mock.assert_not_called()


@pytest.mark.asyncio
async def test_cross_domain_duplicate_seen_on_later_check_is_domain_independent(db_session):
    user = User(username="cross_domain_later_user", telegram_bot_token="t", telegram_chat_id="c")
    user.set_password("p")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    monitor = Monitor(
        user_id=user.id,
        name="Cross Domain Later",
        original_url="https://www.vinted.fr/catalog?search_text=nike",
        params_json="{}",
        domains_json='["vinted.fr", "vinted.de"]',
        last_check_at=datetime.now(timezone.utc),
        items_found_count=0,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    first_domain_item = VintedItem(
        id=7001,
        title="Same Item",
        price=10.0,
        currency="EUR",
        brand="Nike",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.fr/items/7001",
        domain="vinted.fr",
        seller_id=1,
    )
    second_domain_item = VintedItem(
        id=7001,
        title="Same Item",
        price=10.0,
        currency="EUR",
        brand="Nike",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.de/items/7001",
        domain="vinted.de",
        seller_id=1,
    )
    unique_item = VintedItem(
        id=7002,
        title="Unique Item",
        price=12.0,
        currency="EUR",
        brand="Nike",
        size="M",
        condition="New",
        photo_url="",
        item_url="https://www.vinted.de/items/7002",
        domain="vinted.de",
        seller_id=2,
    )

    mock_client = MagicMock()
    mock_client.search_all_domains = AsyncMock(side_effect=[
        [first_domain_item],
        [second_domain_item, unique_item],
    ])
    mock_client.close = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", return_value=db_session), \
         patch("app.scheduler.tasks.process_pending_notifications", AsyncMock()) as notify_mock:
        await check_monitor(monitor.id, scraper_client=mock_client)
        await check_monitor(monitor.id, scraper_client=mock_client)

    seen_items = (await db_session.execute(select(SeenItem).where(SeenItem.user_id == user.id).order_by(SeenItem.vinted_item_id, SeenItem.domain))).scalars().all()
    assert [(item.vinted_item_id, item.domain) for item in seen_items] == [
        (7001, "vinted.de"),
        (7001, "vinted.fr"),
        (7002, "vinted.de"),
    ]

    found_items = (await db_session.execute(select(FoundItem).where(FoundItem.monitor_id == monitor.id).order_by(FoundItem.vinted_item_id, FoundItem.domain))).scalars().all()
    assert [(item.vinted_item_id, item.domain) for item in found_items] == [
        (7001, "vinted.de"),
        (7001, "vinted.fr"),
        (7002, "vinted.de"),
    ]
    assert notify_mock.await_count == 2


@pytest.mark.asyncio
async def test_pending_notification_uses_user_credentials_and_safe_html(db_session):
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    await db_session.execute(update(FoundItem).values(notified=True))
    await db_session.commit()

    user = User(username="notify_payload_user", telegram_bot_token="runtime-test-token", telegram_chat_id="424242", is_telegram_enabled=True)

    user.set_password("p")
    monitor = Monitor(
        user_id=None,
        name="Nike <Monitor> & Deals",
        original_url="u",
        params_json="{}",
        domains_json='["vinted.fr"]',
        last_check_at=datetime.now(timezone.utc),
    )
    db_session.add_all([user, monitor])
    await db_session.commit()
    monitor.user_id = user.id
    item = FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=9001,
        domain="vinted.fr",
        title="Air & Max <Drop>",
        price=25.5,
        currency="EUR",
        brand="Nike",
        size="42",
        condition="Very good",
        photo_url="",
        item_url="https://www.vinted.fr/items/9001",
        seller_id=321,
        notified=False,
    )
    db_session.add(item)
    await db_session.commit()

    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock()

    with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory), \
         patch("app.telegram.bot.get_or_create_bot", return_value=(fake_bot, MagicMock())) as get_bot, \
         patch("app.telegram.notifications.asyncio.sleep", AsyncMock()):
        await process_pending_notifications()

    get_bot.assert_called_once_with("runtime-test-token")
    fake_bot.send_message.assert_awaited_once()
    _, kwargs = fake_bot.send_message.await_args
    assert kwargs["chat_id"] == 424242
    assert "message_thread_id" not in kwargs
    assert kwargs["parse_mode"] == "HTML"
    assert "Nike &lt;Monitor&gt; &amp; Deals" in kwargs["text"]
    assert "Air &amp; Max &lt;Drop&gt;" in kwargs["text"]
    assert "25.5 EUR" in kwargs["text"]
    assert "vinted.fr" in kwargs["text"]
    assert "https://www.vinted.fr/items/9001" in kwargs["text"]
    assert "runtime-test-token" not in kwargs["text"]
    assert "424242" not in kwargs["text"]

    await db_session.refresh(item)
    assert item.notified is True


@pytest.mark.asyncio
async def test_notification_failure_keeps_item_pending(db_session):
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    await db_session.execute(update(FoundItem).values(notified=True))
    await db_session.commit()

    user = User(username="notify_failure_user", telegram_bot_token="runtime-test-token-fail", telegram_chat_id="525252")
    user.set_password("p")
    monitor = Monitor(
        user_id=None,
        name="Failure Monitor",
        original_url="u",
        params_json="{}",
        domains_json='["vinted.fr"]',
        last_check_at=datetime.now(timezone.utc),
    )
    db_session.add_all([user, monitor])
    await db_session.commit()
    monitor.user_id = user.id
    item = FoundItem(
        monitor_id=monitor.id,
        vinted_item_id=9002,
        domain="vinted.fr",
        title="Will Retry",
        price=10.0,
        currency="EUR",
        brand="",
        size="",
        condition="",
        photo_url="",
        item_url="https://www.vinted.fr/items/9002",
        seller_id=1,
        notified=False,
    )
    db_session.add(item)
    await db_session.commit()

    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock(side_effect=RuntimeError("telegram unavailable"))

    with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory), \
         patch("app.telegram.bot.get_or_create_bot", return_value=(fake_bot, MagicMock())):
        await process_pending_notifications()

    await db_session.refresh(item)
    assert item.notified is False


def test_monitor_scheduler_add_remove_update_and_trigger():
    scheduler = MonitorScheduler()

    try:
        scheduler.add_monitor(101, 120)
        assert 101 in scheduler.job_ids
        job_id = scheduler.job_ids[101]
        job = scheduler.scheduler.get_job(job_id)
        assert job is not None
        assert int(job.trigger.interval.total_seconds()) >= 120

        assert scheduler.trigger_now(101) is True
        scheduler.remove_monitor(101)
        assert 101 not in scheduler.job_ids
        assert scheduler.scheduler.get_job(job_id) is None

        scheduler.add_monitor(101, 120)
        scheduler.update_monitor(101, 240)
        updated_job = scheduler.scheduler.get_job(scheduler.job_ids[101])
        assert updated_job is not None
        assert int(updated_job.trigger.interval.total_seconds()) >= 240
    finally:
        if scheduler.scheduler.running:
            scheduler.scheduler.shutdown(wait=False)

@pytest.mark.asyncio
async def test_notification_skipped_if_telegram_disabled(db_session):
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    user = User(username='notify_disabled_user', telegram_bot_token='test-token', telegram_chat_id='123', is_telegram_enabled=False)
    user.set_password('p')
    monitor = Monitor(user_id=None, name='Disabled', original_url='u', params_json='{}', domains_json='["vinted.fr"]', last_check_at=datetime.now(timezone.utc))
    db_session.add_all([user, monitor])
    await db_session.commit()
    monitor.user_id = user.id
    item = FoundItem(monitor_id=monitor.id, vinted_item_id=111, domain='vinted.fr', title='Item', price=10.0, currency='EUR', brand='B', size='S', condition='C', photo_url='', item_url='u', seller_id=1, notified=False)
    db_session.add(item)
    await db_session.commit()

    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock()
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    with patch("app.scheduler.tasks.AsyncSessionLocal", side_effect=session_factory), \
         patch('app.telegram.bot.get_or_create_bot', return_value=(fake_bot, MagicMock())) as get_bot:
        await process_pending_notifications()

    get_bot.assert_not_called()
    fake_bot.send_message.assert_not_awaited()
    await db_session.refresh(item)
    assert item.notified is False
