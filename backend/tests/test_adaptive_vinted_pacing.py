import pytest
import math
from dataclasses import asdict
from app.scheduler.adaptive_pacing import calculate_effective_monitor_intervals

class MockMonitor:
    def __init__(self, id, name, interval_sec, domains_json):
        self.id = id
        self.name = name
        self.interval_sec = interval_sec
        self.domains_json = domains_json

def test_cost_model_and_formula():
    # 21 monitors x 8 domains = 168 slots
    monitors = [
        MockMonitor(i, f"M{i}", 120, '["vinted.fr", "vinted.pl", "vinted.de", "vinted.it", "vinted.es", "vinted.be", "vinted.nl", "vinted.lu"]')
        for i in range(1, 22)
    ]
    
    global_rpm = 30
    domain_rpm = 6
    
    result = calculate_effective_monitor_intervals(
        monitors,
        global_rpm=global_rpm,
        per_domain_rpm=domain_rpm,
        adaptive_enabled=True
    )
    
    assert result.total_domain_slots == 168
    # 168 * 60 / 30 = 336
    assert result.global_sweep_min_interval_seconds == 336
    
    # Each domain is used by 21 monitors
    # 21 * 60 / 6 = 210
    for d, interval in result.per_domain_sweep_min_intervals.items():
        assert interval == 210
        
    for m in result.monitors:
        # max(120, 336, 210) = 336
        assert m.effective_interval_seconds == 336
        assert m.reason == "budget_pressure"

def test_user_interval_not_lowered():
    monitors = [
        MockMonitor(1, "M1", 600, '["vinted.fr"]')
    ]
    
    result = calculate_effective_monitor_intervals(
        monitors,
        global_rpm=30,
        per_domain_rpm=6
    )
    
    # 1 slot * 60 / 30 = 2 seconds global sweep min
    # 1 usage * 60 / 6 = 10 seconds domain sweep min
    # max(600, 2, 10) = 600
    assert result.monitors[0].effective_interval_seconds == 600
    assert result.monitors[0].reason == "user_configured"

def test_per_domain_pressure():
    # M1 uses common domain, M2 uses rare domain
    monitors = [
        MockMonitor(1, "M1", 60, '["common"]'),
        MockMonitor(2, "M2", 60, '["rare"]')
    ]
    # Add more monitors to "common"
    for i in range(3, 13):
        monitors.append(MockMonitor(i, f"M{i}", 60, '["common"]'))
        
    # common: 11 monitors, rare: 1 monitor
    # total slots: 12
    # global_rpm=10 -> 12 * 60 / 10 = 72s
    # domain_rpm=2 -> common: 11 * 60 / 2 = 330s, rare: 1 * 60 / 2 = 30s
    
    result = calculate_effective_monitor_intervals(
        monitors,
        global_rpm=10,
        per_domain_rpm=2
    )
    
    m1 = next(m for m in result.monitors if m.monitor_id == 1)
    m2 = next(m for m in result.monitors if m.monitor_id == 2)
    
    # M1: max(60, 72, 330) = 330
    assert m1.effective_interval_seconds == 330
    # M2: max(60, 72, 30) = 72
    assert m2.effective_interval_seconds == 72

def test_jitter_deterministic():
    monitors = [MockMonitor(1, "M1", 120, '["vinted.fr"]')]
    
    res1 = calculate_effective_monitor_intervals(monitors, 30, 6, jitter_ratio=0.1)
    res2 = calculate_effective_monitor_intervals(monitors, 30, 6, jitter_ratio=0.1)
    
    assert res1.monitors[0].jitter_seconds == res2.monitors[0].jitter_seconds
    assert 0 <= res1.monitors[0].jitter_seconds <= 12

def test_adaptive_disabled():
    monitors = [MockMonitor(1, "M1", 60, '["vinted.fr"]')]
    # global pressure would suggest 120s
    
    result = calculate_effective_monitor_intervals(
        monitors,
        global_rpm=0.5, # 1 slot * 60 / 0.5 = 120s
        per_domain_rpm=6,
        adaptive_enabled=False
    )
    
    assert result.monitors[0].effective_interval_seconds == 60
    assert result.monitors[0].reason == "adaptive_disabled"

@pytest.mark.asyncio
async def test_limiter_logic():
    from app.scheduler.vinted_rate_limiter import VintedRateLimiter
    import time
    
    # RPM=60 means 1 req/sec
    limiter = VintedRateLimiter(global_rpm=60, domain_rpm=60)
    
    # Pre-drain buckets to force wait on next acquire
    limiter._global_bucket = 0.0
    limiter._domain_buckets["vinted.fr"] = 0.0
    
    start = time.monotonic()
    # This should wait for refill to reach 1.0 (approx 1 second)
    await limiter.acquire("vinted.fr")
    end = time.monotonic()
    
    assert end - start >= 0.8

@pytest.mark.asyncio
async def test_limiter_backoff():
    from app.scheduler.vinted_rate_limiter import VintedRateLimiter
    import time
    
    limiter = VintedRateLimiter(global_rpm=1000, domain_rpm=1000)
    
    # Report 429
    limiter.report_status("vinted.fr", 429)
    
    diag = limiter.get_diagnostics()
    assert "vinted.fr" in diag["active_backoffs"]
    assert diag["active_backoffs"]["vinted.fr"] >= 119 # Default min backoff 120s
    
    # Report 200 should clear backoff level but NOT necessarily the timer 
    # (actually my implementation clears level but not until timer expires for simplicity in Phase 1)
    # Wait, report_status(200) sets level=0. 
    # But acquire() checks domain_backoff_until.
    
    limiter.report_status("vinted.fr", 200)
    # Level is 0, but backoff_until is still in future.
    
@pytest.mark.asyncio
async def test_limiter_retry_after():
    from app.scheduler.vinted_rate_limiter import VintedRateLimiter
    
    limiter = VintedRateLimiter(global_rpm=1000, domain_rpm=1000)
    limiter.report_status("vinted.fr", 429, retry_after=50)
    
    diag = limiter.get_diagnostics()
    assert 45 <= diag["active_backoffs"]["vinted.fr"] <= 51
