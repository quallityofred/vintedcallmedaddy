import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.scraper.client import VintedClient

@pytest.fixture
def mock_client():
    rate_limiter = MagicMock()
    # Mock rate_limiter.acquire to be a coroutine
    rate_limiter.acquire = AsyncMock()
    return VintedClient(rate_limiter=rate_limiter)

@pytest.mark.asyncio
async def test_fetch_catalog_hydration_items_fetches_html_and_parses_items(mock_client):
    # Mock fetch_catalog_html
    html = '<html><script>self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":123,\\\"title\\":\\\"Item 1\\\"}]}}"])</script></html>'
    mock_client.fetch_catalog_html = AsyncMock(return_value=html)
    
    items = await mock_client.fetch_catalog_hydration_items("https://vinted.pl/catalog?...")
    
    assert len(items) == 1
    assert items[0]["id"] == "123"
    assert items[0]["title"] == "Item 1"

@pytest.mark.asyncio
async def test_fetch_catalog_hydration_items_uses_domain_from_url(mock_client):
    mock_client.fetch_catalog_html = AsyncMock(return_value='<html><script>self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":1,\\\"path\\":\\\"/p\\\"}]}}"])</script></html>')
    
    items = await mock_client.fetch_catalog_hydration_items("https://vinted.de/catalog?...", domain="vinted.de")
    assert items[0]["url"] == "https://www.vinted.de/p"

@pytest.mark.asyncio
async def test_fetch_catalog_hydration_items_preserves_parser_order(mock_client):
    html = '<html><script>self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":1},{\\"id\\":2}]}}"])</script></html>'
    mock_client.fetch_catalog_html = AsyncMock(return_value=html)
    items = await mock_client.fetch_catalog_hydration_items("...")
    assert [i["id"] for i in items] == ["1", "2"]

@pytest.mark.asyncio
async def test_fetch_catalog_hydration_items_does_not_require_dom_cards(mock_client):
    # Payload in script only
    html = '<script>self.__next_f.push([1,"{\\"items\\":{\\"items\\":[{\\"id\\":1}]}}"])</script>'
    mock_client.fetch_catalog_html = AsyncMock(return_value=html)
    items = await mock_client.fetch_catalog_hydration_items("...")
    assert len(items) == 1

@pytest.mark.asyncio
async def test_fetch_catalog_hydration_items_handles_empty_hydration(mock_client):
    mock_client.fetch_catalog_html = AsyncMock(return_value='<html></html>')
    items = await mock_client.fetch_catalog_hydration_items("...")
    assert items == []

@pytest.mark.asyncio
async def test_fetch_catalog_hydration_items_propagates_http_errors(mock_client):
    mock_client.fetch_catalog_html = AsyncMock(return_value="")
    items = await mock_client.fetch_catalog_hydration_items("...")
    assert items == []

@pytest.mark.asyncio
async def test_new_hydration_fetch_method_is_not_called_by_existing_search_paths(mock_client):
    # Mock internal methods
    mock_client.fetch_catalog_hydration_items = AsyncMock()
    mock_client.search = AsyncMock()
    
    # Simulate standard scheduler call
    await mock_client.search("vinted.pl", {})
    
    # Assert hydration was not called
    assert not mock_client.fetch_catalog_hydration_items.called
