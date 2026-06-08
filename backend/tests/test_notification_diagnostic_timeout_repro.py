from __future__ import annotations

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.scheduler import tasks

@pytest.mark.asyncio
async def test_process_pending_notifications_dry_run_not_blocked(monkeypatch):
    # Mock collect_pending_notification_candidates to return immediately
    mock_collect = AsyncMock(return_value=([], {
        "pending_total": 0,
        "telegram_bot_configured": False,
        "telegram_chat_configured": False,
        "uses_group_rate": False,
    }))
    monkeypatch.setattr(tasks, "collect_pending_notification_candidates", mock_collect)

    # Simulate a long-running lock holder
    lock_acquired = asyncio.Event()
    test_can_finish = asyncio.Event()
    
    original_lock = tasks._notification_lock
    
    async def slow_task():
        async with original_lock:
            lock_acquired.set()
            print("Lock acquired by slow task")
            await test_can_finish.wait()
            print("Slow task releasing lock")
            
    # Start the slow task
    bg_task = asyncio.create_task(slow_task())
    await lock_acquired.wait()
    
    print("Attempting dry-run notification (should NOT be blocked)")
    start_time = time.monotonic()
    try:
        # We expect this to NOT be blocked now because it's dry_run=True
        await asyncio.wait_for(tasks.process_pending_notifications(dry_run=True), timeout=0.5)
        blocked = False
    except asyncio.TimeoutError:
        print("Timeout reached!")
        blocked = True
    
    duration = time.monotonic() - start_time
    print(f"Duration: {duration}")
    
    # Clean up
    test_can_finish.set()
    await bg_task
    
    assert blocked is False, "Expected dry_run NOT to be blocked by the lock"
    assert mock_collect.called
