import asyncio
import time
import pytest
from unittest.mock import MagicMock, patch
from contextlib import asynccontextmanager

from app.scraper.client import HttpBudgetLimiter, VintedClient
from app.config import Settings

@pytest.fixture
def mock_settings():
    settings = Settings()
    settings.scraper_global_http_concurrency = 2
    settings.scraper_domain_http_concurrency = 1
    settings.scraper_domain_cooldown_seconds = 1
    return settings

@pytest.mark.asyncio
async def test_global_concurrency_limit(mock_settings):
    with patch("app.scraper.client.settings", mock_settings):
        limiter = HttpBudgetLimiter()
        
        # Should be able to acquire 2 global slots
        async with limiter.acquire("vinted.pl"):
            async with limiter.acquire("vinted.fr"):
                # Third one should block (we'll use a timeout to verify)
                try:
                    await asyncio.wait_for(limiter.acquire("vinted.it").__aenter__(), timeout=0.1)
                    pytest.fail("Should have timed out")
                except asyncio.TimeoutError:
                    pass

@pytest.mark.asyncio
async def test_per_domain_concurrency_limit(mock_settings):
    with patch("app.scraper.client.settings", mock_settings):
        limiter = HttpBudgetLimiter()
        
        # Should be able to acquire 1 slot for a domain
        async with limiter.acquire("vinted.pl"):
            # Second one for same domain should block
            try:
                await asyncio.wait_for(limiter.acquire("vinted.pl").__aenter__(), timeout=0.1)
                pytest.fail("Should have timed out")
            except asyncio.TimeoutError:
                pass

@pytest.mark.asyncio
async def test_cooldown_behavior(mock_settings):
    with patch("app.scraper.client.settings", mock_settings):
        limiter = HttpBudgetLimiter()
        
        domain = "vinted.pl"
        limiter.report_block(domain)
        
        assert limiter.is_in_cooldown(domain) is True
        
        with pytest.raises(RuntimeError, match="is in cooldown"):
            async with limiter.acquire(domain):
                pass
        
        # Wait for cooldown to expire
        await asyncio.sleep(1.1)
        assert limiter.is_in_cooldown(domain) is False
        
        # Should be able to acquire now
        async with limiter.acquire(domain):
            pass

@pytest.mark.asyncio
async def test_different_domains_concurrency(mock_settings):
    with patch("app.scraper.client.settings", mock_settings):
        limiter = HttpBudgetLimiter()
        
        # Different domains can run concurrently up to global limit
        async with limiter.acquire("vinted.pl"):
            async with limiter.acquire("vinted.fr"):
                stats = limiter.get_stats()
                assert stats["scraper_active_http_requests"] == 2
                assert stats["scraper_active_http_requests_by_domain"]["vinted.pl"] == 1
                assert stats["scraper_active_http_requests_by_domain"]["vinted.fr"] == 1


@pytest.mark.asyncio
async def test_item_detail_fetch_uses_http_budget(monkeypatch):
    class FakeBudget:
        def __init__(self):
            self.acquired_domains = []

        @asynccontextmanager
        async def acquire(self, domain):
            self.acquired_domains.append(domain)
            yield

        def report_block(self, domain):
            pass

    class FakeRateLimiter:
        def __init__(self):
            self.acquired_domains = []

        async def acquire(self, domain):
            self.acquired_domains.append(domain)

        def report_success(self, domain):
            pass

        def report_error(self, domain):
            pass

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "item": {
                    "id": 123,
                    "created_at": "2026-06-06T10:00:00Z",
                    "catalog_id": 1231,
                }
            }

    class FakeSession:
        async def get(self, *args, **kwargs):
            return FakeResponse()

    fake_budget = FakeBudget()
    fake_rate_limiter = FakeRateLimiter()
    client = VintedClient(rate_limiter=fake_rate_limiter)
    monkeypatch.setattr("app.scraper.client._http_budget", fake_budget)
    monkeypatch.setattr(client, "_warmup_session", lambda domain: asyncio.sleep(0))
    monkeypatch.setattr(client, "_ensure_session", lambda domain: asyncio.sleep(0, result=FakeSession()))

    detail = await client.fetch_item_detail("vinted.pl", 123)

    assert fake_rate_limiter.acquired_domains == ["vinted.pl"]
    assert fake_budget.acquired_domains == ["vinted.pl"]
    assert detail is not None
    assert detail.catalog_ids == frozenset({"1231"})
