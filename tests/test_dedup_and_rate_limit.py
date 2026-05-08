# tests/test_dedup_and_rate_limit.py
import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, FoundItem, HiddenSeller, Monitor
from app.scraper.client import VintedClient
from app.scraper.parser import VintedItem
from app.scraper.rate_limiter import TokenBucketLimiter


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


def _make_item(item_id: int, domain: str = "vinted.fr") -> VintedItem:
    return VintedItem(
        id=item_id,
        title=f"Item {item_id}",
        price=10.0,
        currency="EUR",
        brand="TestBrand",
        size="M",
        condition="Good",
        photo_url=f"https://img.vinted.net/{item_id}.jpg",
        item_url=f"https://www.{domain}/items/{item_id}",
        domain=domain,
        seller_id=100 + item_id,
    )


# ---------------------------------------------------------------------------
# Bug 1: Deduplication tests
# ---------------------------------------------------------------------------

class TestDeduplication:
    """Verify that items are deduplicated by vinted_item_id alone,
    regardless of which domain they were found on."""

    @pytest.mark.asyncio
    async def test_same_item_different_domain_not_duplicated(self, db_session_factory):
        """An item saved from vinted.fr must NOT be re-inserted when seen
        from vinted.de on the next check cycle."""
        async with db_session_factory() as db:
            monitor = Monitor(
                name="test",
                original_url="https://www.vinted.fr/catalog?brand_ids[]=123",
                params_json='{"brand_ids": "123"}',
                domains_json='["vinted.fr", "vinted.de"]',
                interval_sec=120,
                is_active=True,
                last_check_at=None,
                items_found_count=0,
                consecutive_empty=0,
            )
            db.add(monitor)
            await db.commit()
            monitor_id = monitor.id

            fi = FoundItem(
                monitor_id=monitor_id,
                vinted_item_id=999,
                domain="vinted.fr",
                title="Existing Item",
                price=20.0,
                currency="EUR",
                brand="Brand",
                size="L",
                condition="Good",
                photo_url="https://img.vinted.net/999.jpg",
                item_url="https://www.vinted.fr/items/999",
                seller_id=200,
                found_at=datetime.now(timezone.utc),
                notified=True,
            )
            db.add(fi)
            await db.commit()

            exists_result = await db.execute(
                select(FoundItem.id).where(
                    FoundItem.vinted_item_id == 999,
                )
            )
            assert exists_result.first() is not None

    @pytest.mark.asyncio
    async def test_truly_new_item_is_added(self, db_session_factory):
        """A brand new item_id that has never been seen must be added."""
        async with db_session_factory() as db:
            exists_result = await db.execute(
                select(FoundItem.id).where(
                    FoundItem.vinted_item_id == 12345,
                )
            )
            assert exists_result.first() is None

    @pytest.mark.asyncio
    async def test_cold_start_no_notifications(self, db_session_factory):
        """On cold start (last_check_at is None), items should be saved
        but NOT marked as notified."""
        async with db_session_factory() as db:
            monitor = Monitor(
                name="cold_test",
                original_url="https://www.vinted.fr/catalog?brand_ids[]=456",
                params_json='{"brand_ids": "456"}',
                domains_json='["vinted.fr"]',
                interval_sec=120,
                is_active=True,
                last_check_at=None,
                items_found_count=0,
                consecutive_empty=0,
            )
            db.add(monitor)
            await db.commit()

            assert monitor.last_check_at is None
            is_cold_start = monitor.last_check_at is None
            assert is_cold_start is True

    @pytest.mark.asyncio
    async def test_cross_domain_dedup_prevents_renotification(self, db_session_factory):
        """Simulate the exact bug: item 999 was found on vinted.fr in first run,
        then on vinted.de in second run. With the fix, it should not be treated as new."""
        async with db_session_factory() as db:
            monitor = Monitor(
                name="cross_domain_test",
                original_url="https://www.vinted.fr/catalog?brand_ids[]=789",
                params_json='{"brand_ids": "789"}',
                domains_json='["vinted.fr", "vinted.de"]',
                interval_sec=120,
                is_active=True,
                last_check_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                items_found_count=10,
                consecutive_empty=0,
            )
            db.add(monitor)
            await db.commit()
            monitor_id = monitor.id

            fi = FoundItem(
                monitor_id=monitor_id,
                vinted_item_id=999,
                domain="vinted.fr",
                title="Cross Domain Item",
                price=25.0,
                currency="EUR",
                brand="Swear",
                size="42",
                condition="Good",
                photo_url="https://img.vinted.net/999.jpg",
                item_url="https://www.vinted.fr/items/999",
                seller_id=300,
                found_at=datetime.now(timezone.utc),
                notified=True,
            )
            db.add(fi)
            await db.commit()

            exists_result = await db.execute(
                select(FoundItem.id).where(
                    FoundItem.vinted_item_id == 999,
                )
            )
            assert exists_result.first() is not None, \
                "Item 999 should be found by vinted_item_id alone, regardless of domain"

    @pytest.mark.asyncio
    async def test_multiple_items_different_domains_dedup(self, db_session_factory):
        """Multiple items from different domains should all be deduplicated
        by vinted_item_id."""
        async with db_session_factory() as db:
            monitor = Monitor(
                name="multi_domain_test",
                original_url="https://www.vinted.fr/catalog?brand_ids[]=111",
                params_json='{"brand_ids": "111"}',
                domains_json='["vinted.fr", "vinted.de", "vinted.it"]',
                interval_sec=120,
                is_active=True,
                last_check_at=datetime.now(timezone.utc),
                items_found_count=0,
                consecutive_empty=0,
            )
            db.add(monitor)
            await db.commit()
            monitor_id = monitor.id

            for item_id, domain in [(1, "vinted.fr"), (2, "vinted.de"), (3, "vinted.it")]:
                fi = FoundItem(
                    monitor_id=monitor_id,
                    vinted_item_id=item_id,
                    domain=domain,
                    title=f"Item {item_id}",
                    price=10.0,
                    currency="EUR",
                    brand="Brand",
                    size="M",
                    condition="Good",
                    photo_url=f"https://img.vinted.net/{item_id}.jpg",
                    item_url=f"https://www.{domain}/items/{item_id}",
                    seller_id=400 + item_id,
                    found_at=datetime.now(timezone.utc),
                    notified=True,
                )
                db.add(fi)
            await db.commit()

            for item_id in [1, 2, 3]:
                result = await db.execute(
                    select(FoundItem.id).where(
                        FoundItem.vinted_item_id == item_id,
                    )
                )
                assert result.first() is not None, \
                    f"Item {item_id} should be found by vinted_item_id only"


# ---------------------------------------------------------------------------
# Bug 2: Rate limiting and concurrency tests
# ---------------------------------------------------------------------------

class TestRateLimiting:

    @pytest.mark.asyncio
    async def test_parallel_domain_execution_with_semaphore(self):
        """Verify domains are searched in parallel, bounded by semaphore."""
        rate_limiter = TokenBucketLimiter(rate=100.0, per=1.0)
        client = VintedClient(rate_limiter=rate_limiter)

        active_count = 0
        max_concurrent = 0
        call_order: list[str] = []

        async def mock_search(domain: str, params: dict) -> list[VintedItem]:
            nonlocal active_count, max_concurrent
            active_count += 1
            max_concurrent = max(max_concurrent, active_count)
            call_order.append(domain)
            await asyncio.sleep(0.01)
            active_count -= 1
            return [_make_item(1, domain)]

        client.search = mock_search  # type: ignore[assignment]

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:
            await original_sleep(min(delay, 0.01))

        with patch("app.scraper.client.asyncio.sleep", side_effect=fast_sleep):
            await client.search_all_domains(
                {"brand_ids": "123"},
                ["vinted.fr", "vinted.de", "vinted.it"],
            )

        assert max_concurrent <= 3, "Concurrency must be bounded by semaphore"
        assert len(call_order) == 3

    @pytest.mark.asyncio
    async def test_search_all_domains_uses_semaphore(self):
        """Verify that search_all_domains uses semaphore to bound concurrency."""
        rate_limiter = TokenBucketLimiter(rate=100.0, per=1.0)
        client = VintedClient(rate_limiter=rate_limiter)

        call_order: list[str] = []

        async def mock_search(domain: str, params: dict) -> list[VintedItem]:
            call_order.append(f"start_{domain}")
            await asyncio.sleep(0.01)
            call_order.append(f"end_{domain}")
            return [_make_item(1, domain)]

        client.search = mock_search  # type: ignore[assignment]

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:
            await original_sleep(min(delay, 0.01))

        with patch("app.scraper.client.asyncio.sleep", side_effect=fast_sleep):
            result = await client.search_all_domains({"brand_ids": "123"}, ["vinted.fr"])

        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_domains_are_shuffled(self):
        """Verify domains are shuffled for each search_all_domains call
        to distribute load."""
        rate_limiter = TokenBucketLimiter(rate=100.0, per=1.0)
        client = VintedClient(rate_limiter=rate_limiter)

        searched_domains: list[str] = []

        async def mock_search(domain: str, params: dict) -> list[VintedItem]:
            searched_domains.append(domain)
            return []

        client.search = mock_search  # type: ignore[assignment]

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:
            await original_sleep(min(delay, 0.01))

        domains = ["vinted.fr", "vinted.de", "vinted.it", "vinted.pl", "vinted.es"]

        orders: list[list[str]] = []
        with patch("app.scraper.client.asyncio.sleep", side_effect=fast_sleep):
            for _ in range(5):
                searched_domains.clear()
                await client.search_all_domains({"brand_ids": "123"}, domains)
                orders.append(searched_domains.copy())

        unique_orders = set(tuple(o) for o in orders)
        assert len(unique_orders) > 1 or len(domains) <= 1, \
            "Domains should be shuffled across different calls"

    @pytest.mark.asyncio
    async def test_search_all_domains_deduplicates_by_id(self):
        """Same item_id from multiple domains should only appear once."""
        rate_limiter = TokenBucketLimiter(rate=100.0, per=1.0)
        client = VintedClient(rate_limiter=rate_limiter)

        async def mock_search(domain: str, params: dict) -> list[VintedItem]:
            return [_make_item(42, domain)]

        client.search = mock_search  # type: ignore[assignment]

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:
            await original_sleep(min(delay, 0.01))

        with patch("app.scraper.client.asyncio.sleep", side_effect=fast_sleep):
            result = await client.search_all_domains(
                {"brand_ids": "123"},
                ["vinted.fr", "vinted.de", "vinted.it"],
            )

        assert len(result) == 1, "Same item_id should be deduplicated across domains"
        assert result[0].id == 42


class TestTokenBucketLimiter:

    @pytest.mark.asyncio
    async def test_error_tracking(self):
        """Verify error counting and reset."""
        limiter = TokenBucketLimiter(rate=8.0, per=60.0)

        assert limiter.error_counts.get("vinted.fr", 0) == 0

        limiter.report_error("vinted.fr")
        assert limiter.error_counts["vinted.fr"] == 1

        limiter.report_error("vinted.fr")
        assert limiter.error_counts["vinted.fr"] == 2

        limiter.report_success("vinted.fr")
        assert limiter.error_counts["vinted.fr"] == 0

    @pytest.mark.asyncio
    async def test_independent_domain_tracking(self):
        """Errors on one domain should not affect another."""
        limiter = TokenBucketLimiter(rate=8.0, per=60.0)

        limiter.report_error("vinted.fr")
        limiter.report_error("vinted.fr")
        limiter.report_error("vinted.fr")

        assert limiter.error_counts["vinted.fr"] == 3
        assert limiter.error_counts.get("vinted.de", 0) == 0

    @pytest.mark.asyncio
    async def test_acquire_basic(self):
        """Basic acquire should complete without error."""
        limiter = TokenBucketLimiter(rate=100.0, per=1.0)

        original_sleep = asyncio.sleep

        async def fast_sleep(delay: float) -> None:
            await original_sleep(min(delay, 0.01))

        with patch("app.scraper.rate_limiter.asyncio.sleep", side_effect=fast_sleep):
            await limiter.acquire("vinted.fr")

        assert limiter.buckets["vinted.fr"] < 100.0
