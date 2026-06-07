from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import asyncio

@dataclass
class MonitorDiagnostics:
    monitor_id: int
    last_check_at: Optional[datetime] = None
    last_check_source: str = "unknown"
    domains_processed: List[str] = field(default_factory=list)
    items_found_count_by_domain: Dict[str, int] = field(default_factory=dict)
    last_error: Optional[str] = None


@dataclass
class DiagnosticJob:
    job_id: str
    monitor_id: int
    status: str
    source: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    safe_error: Optional[str] = None

class DiagnosticsRegistry:
    def __init__(self):
        self._diagnostics: Dict[int, MonitorDiagnostics] = {}
        self._jobs: Dict[str, DiagnosticJob] = {}
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

    async def start_job(self, job_id: str, monitor_id: int, source: str) -> DiagnosticJob:
        job = DiagnosticJob(
            job_id=job_id,
            monitor_id=monitor_id,
            status="running",
            source=source,
            started_at=datetime.utcnow(),
        )
        async with self._lock:
            self._jobs[job_id] = job
        return job

    async def complete_job(self, job_id: str, result: Dict[str, Any]) -> Optional[DiagnosticJob]:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.result = result
            job.safe_error = None
            return job

    async def fail_job(self, job_id: str, safe_error: str) -> Optional[DiagnosticJob]:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.status = "failed"
            job.completed_at = datetime.utcnow()
            job.safe_error = safe_error
            job.result = None
            return job

    async def get_job(self, job_id: str, monitor_id: int) -> Optional[DiagnosticJob]:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.monitor_id != monitor_id:
                return None
            return job

registry = DiagnosticsRegistry()
