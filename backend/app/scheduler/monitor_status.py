from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from app.models import Monitor

def reconcile_monitor_check_status(monitor: Monitor, is_running_in_registry: bool) -> Dict[str, Any]:
    """
    Reconciles the monitor check status from the database with the in-memory registry.
    Detects stale 'running' states and inconsistent timestamps.
    """
    db_status = monitor.last_check_status
    started_at = monitor.last_check_started_at
    completed_at = monitor.last_check_completed_at
    
    # 1. Stale running check: DB says running but registry says inactive
    is_stale_running = (db_status == "running" and not is_running_in_registry)
    
    # 2. Inconsistent timestamps: Started after completed, and not currently running
    is_inconsistent_check_state = False
    if started_at and completed_at:
        if started_at > completed_at and not is_running_in_registry:
            is_inconsistent_check_state = True
            
    # 3. Effective status for display
    effective_status = db_status
    if is_running_in_registry:
        effective_status = "running"
    elif is_stale_running:
        effective_status = "failed"
        
    # 4. Explanation
    explanation = "Status unknown."
    if effective_status is None:
        explanation = "This monitor has not been checked yet."
    elif is_running_in_registry:
        explanation = "Check is currently running."
    elif is_stale_running:
        explanation = "Check was marked running but no active process found (stale)."
    elif is_inconsistent_check_state:
        explanation = "Monitor check state is inconsistent (last start after last completion)."
    elif effective_status == "baseline_created":
        explanation = "Tracking baseline initialized. Future new items will appear here."
    elif effective_status == "success_zero_items":
        explanation = "Checked successfully, but scraper returned 0 items."
    elif effective_status == "success_no_new_items":
        explanation = "Checked successfully. No new items found."
    elif effective_status == "success_new_items":
        explanation = "Checked successfully. New items were found."
    elif effective_status == "failed":
        explanation = f"Check failed: {monitor.last_error or 'Unknown error'}"

    return {
        "effective_status": effective_status,
        "is_stale_running": is_stale_running,
        "is_inconsistent_check_state": is_inconsistent_check_state,
        "explanation": explanation,
    }
