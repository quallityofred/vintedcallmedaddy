from pydantic import BaseModel
from typing import List, Optional

class AckNoNotifyRequest(BaseModel):
    dry_run: bool = True
    monitor_ids: Optional[List[int]] = None
    domains: Optional[List[str]] = None
    older_than_minutes: int = 1440
    include_inactive: bool = True
    include_active: bool = False
    sample_limit: int = 10
    reason: Optional[str] = None
    confirm: Optional[str] = None
    extra_confirm: Optional[List[str]] = None

class RetentionCleanupRequest(BaseModel):
    dry_run: bool = True
    monitor_ids: Optional[List[int]] = None
    domains: Optional[List[str]] = None
    include_found_items: bool = True
    include_seen_items: bool = True
    found_items_retention_days: int = 14
    found_items_max_per_monitor_domain: int = 128
    seen_items_max_per_monitor_domain: int = 192
    sample_limit: int = 10
    reason: Optional[str] = None
    confirm: Optional[str] = None
    extra_confirm: Optional[List[str]] = None

class ColdStartResetRequest(BaseModel):
    dry_run: bool = True
    domains: Optional[List[str]] = None
    clear_seen_items: bool = True
    clear_found_items: bool = False
    reset_last_checked: bool = True
    require_monitor_inactive: bool = True
    sample_limit: int = 10
    reason: Optional[str] = None
    confirm: Optional[str] = None
    extra_confirm: Optional[List[str]] = None
