from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import asyncio

@dataclass
class MonitorDiagnostics:
    monitor_id: int
    last_check_at: Optional[datetime] = None
    last_check_source: str = "unknown"
    domains_processed: List[str] = field(default_factory=list)
    items_found_count_by_domain: Dict[str, int] = field(default_factory=dict)
    last_error: Optional[str] = None

class DiagnosticsRegistry:
    def __init__(self):
        self._diagnostics: Dict[int, MonitorDiagnostics] = {}
        self._lock = asyncio.Lock()

    async def record_check(self, monitor_id: int, source: str, domain_counts: Dict[str, int], error: Optional[str] = None):
        async with self._lock:
            self._diagnostics[monitor_id] = MonitorDiagnostics(
                monitor_id=monitor_id,
                last_check_at=datetime.utcnow(),
                last_check_source=source,
                domains_processed=list(domain_counts.keys()),
                items_found_count_by_domain=domain_counts,
                last_error=error
            )

    async def get_check(self, monitor_id: int) -> Optional[MonitorDiagnostics]:
        async with self._lock:
            return self._diagnostics.get(monitor_id)

registry = DiagnosticsRegistry()
