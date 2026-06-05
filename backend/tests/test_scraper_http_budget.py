import asyncio
import time
import pytest
from unittest.mock import MagicMock, patch

from app.scraper.client import HttpBudgetLimiter
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
