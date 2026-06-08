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
