from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MonitorPacingInfo:
    monitor_id: int
    name: str
    configured_interval_seconds: int
    selected_domains_count: int
    selected_domains: List[str]
    domain_budget_min_interval_seconds: int
    effective_interval_seconds: int
    jitter_seconds: int
    reason: str


@dataclass
class PacingCalculationResult:
    adaptive_enabled: bool
    active_monitor_count: int
    total_domain_slots: int
    global_rpm: int
    per_domain_rpm: int
    global_sweep_min_interval_seconds: int
    domain_usage: Dict[str, int]
    per_domain_sweep_min_intervals: Dict[str, int]
    monitors: List[MonitorPacingInfo] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def calculate_effective_monitor_intervals(
    active_monitors: List[Any],
    global_rpm: int,
    per_domain_rpm: int,
    jitter_ratio: float = 0.10,
    adaptive_enabled: bool = True,
) -> PacingCalculationResult:
    """
    Calculate effective intervals for active monitors based on RPM budgets.
    Does not mutate any input data or database state.
    """
    # 1. Theoretical sweep pressure
    total_domain_slots = 0
    domain_usage: Dict[str, int] = {}

    monitor_data = []
    for m in active_monitors:
        try:
            # We assume m has domains_json and interval_sec (Monitor model)
            domains = json.loads(getattr(m, "domains_json", "[]"))
            if not isinstance(domains, list):
                domains = []
        except (json.JSONDecodeError, TypeError):
            domains = []

        m_interval = getattr(m, "interval_sec", 120)

        monitor_data.append(
            {
                "id": m.id,
                "name": m.name,
                "interval_sec": m_interval,
                "domains": domains,
            }
        )

        total_domain_slots += len(domains)
        for d in domains:
            domain_usage[d] = domain_usage.get(d, 0) + 1

    # 2. Global sweep minimum
    # Global budget for a full sweep of all monitors:
    # If we have 168 domain slots and 30 RPM limit, we need 168 / 30 = 5.6 minutes = 336 seconds per sweep.
    global_sweep_min = (
        math.ceil(total_domain_slots * 60 / global_rpm) if global_rpm > 0 else 0
    )

    # 3. Per-domain sweep minimum
    # If a domain is checked by 21 monitors and limit is 6 RPM, we need 21 / 6 = 3.5 minutes = 210 seconds per sweep of that domain.
    per_domain_sweep_min = (
        {d: math.ceil(count * 60 / per_domain_rpm) for d, count in domain_usage.items()}
        if per_domain_rpm > 0
        else {}
    )

    # 4. Effective interval
    result = PacingCalculationResult(
        adaptive_enabled=adaptive_enabled,
        active_monitor_count=len(active_monitors),
        total_domain_slots=total_domain_slots,
        global_rpm=global_rpm,
        per_domain_rpm=per_domain_rpm,
        global_sweep_min_interval_seconds=global_sweep_min,
        domain_usage=domain_usage,
        per_domain_sweep_min_intervals=per_domain_sweep_min,
    )

    for m in monitor_data:
        m_id = m["id"]
        m_name = m["name"]
        m_interval = m["interval_sec"]
        m_domains = m["domains"]

        # Max selected-domain sweep minimum
        max_domain_min = 0
        if m_domains:
            max_domain_min = max(
                (per_domain_sweep_min.get(d, 0) for d in m_domains), default=0
            )

        # Theoretical budget min for this monitor
        budget_min = max(global_sweep_min, max_domain_min)

        # Effective is max of configured and budget (never lower than user config)
        effective = max(m_interval, budget_min) if adaptive_enabled else m_interval

        # Jitter: deterministic per monitor_id within configured ratio
        jitter_max = int(effective * jitter_ratio)
        if jitter_max > 0:
            # Deterministic pseudo-random based on id
            # Linear congruential generator parameters for simple deterministic shuffle
            seed = (m_id * 9301 + 49297) % 233280
            jitter_seconds = seed % (jitter_max + 1)
        else:
            jitter_seconds = 0

        reason = "budget_pressure" if effective > m_interval else "user_configured"
        if not adaptive_enabled:
            reason = "adaptive_disabled"

        result.monitors.append(
            MonitorPacingInfo(
                monitor_id=m_id,
                name=m_name,
                configured_interval_seconds=m_interval,
                selected_domains_count=len(m_domains),
                selected_domains=m_domains,
                domain_budget_min_interval_seconds=budget_min,
                effective_interval_seconds=effective,
                jitter_seconds=jitter_seconds,
                reason=reason,
            )
        )

    return result
