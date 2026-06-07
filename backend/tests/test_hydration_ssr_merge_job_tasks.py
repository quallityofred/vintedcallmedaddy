import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.scheduler.tasks import run_hydration_ssr_merge_job

@pytest.mark.asyncio
async def test_run_hydration_ssr_merge_job_concurrent_fetches():
    mock_monitor = MagicMock()
    mock_monitor.id = 22
    mock_monitor.original_url = "https://www.vinted.pl/catalog?catalog[]=1231"
    mock_monitor.domains_json = '["vinted.pl", "vinted.fr"]'
    
    with patch("app.scheduler.tasks.get_session_factory") as mock_session_factory, \
         patch("app.scheduler.tasks.select") as mock_select, \
         patch("app.scheduler.tasks.VintedClient") as mock_client_cls, \
         patch("app.scheduler.diagnostics.registry") as mock_registry, \
         patch("app.scheduler.tasks.parse_catalog_ssr_photo_map") as mock_ssr, \
         patch("app.scheduler.tasks.extract_hydration_items") as mock_hydration:
        
        mock_db = AsyncMock()
        mock_session_factory.return_value = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_db
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_monitor
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        mock_client = AsyncMock()
        mock_client.fetch_catalog_html = AsyncMock(return_value="<html></html>")
        mock_client_cls.return_value = mock_client
        
        mock_hydration.return_value = []
        mock_ssr.return_value = {}

        await run_hydration_ssr_merge_job(22, "test_job")
        
        assert mock_client.fetch_catalog_html.call_count == 2
        assert mock_registry.record_check.called
