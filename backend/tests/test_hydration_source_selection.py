import pytest
from unittest.mock import MagicMock, patch
from app.scraper.source_selector import should_use_hydration_source

def test_hydration_source_disabled_by_default_uses_existing_api_path():
    with patch("app.scraper.source_selector.get_settings") as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.monitor_hydration_source_enabled = False
        mock_get_settings.return_value = mock_settings
        
        # Test catalog monitor (should still be false)
        params = {"catalog[]": "1231"}
        assert should_use_hydration_source(params) is False

def test_hydration_source_enabled_for_catalog_monitor():
    with patch("app.scraper.source_selector.get_settings") as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.monitor_hydration_source_enabled = True
        mock_get_settings.return_value = mock_settings
        
        # Test catalog monitor
        params = {"catalog[]": "1231"}
        assert should_use_hydration_source(params) is True

def test_hydration_source_not_enabled_for_brand_only_monitor():
    with patch("app.scraper.source_selector.get_settings") as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.monitor_hydration_source_enabled = True
        mock_get_settings.return_value = mock_settings
        
        # Test brand-only monitor
        params = {"brand_ids[]": "53"}
        assert should_use_hydration_source(params) is False

def test_hydration_source_selector_detects_catalog_array_param():
    with patch("app.scraper.source_selector.get_settings") as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.monitor_hydration_source_enabled = True
        mock_get_settings.return_value = mock_settings
        
        assert should_use_hydration_source({"catalog[]": "1231"}) is True
        assert should_use_hydration_source({"catalog_ids[]": "1231"}) is True
        assert should_use_hydration_source({"catalog_id": "1231"}) is True
        assert should_use_hydration_source({"catalog": "1231"}) is True
