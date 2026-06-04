import asyncio
import argparse
import json
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add parent directory to sys.path to import app modules
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_session_factory
from app.models import Monitor
from app.scraper.url_parser import parse_vinted_url, normalize_vinted_monitor_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def normalize_all_monitors(confirm: bool = False):
    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(select(Monitor))
        monitors = result.scalars().all()
        
        total = len(monitors)
        dirty_count = 0
        fixed_count = 0
        
        logger.info(f"Scanning {total} monitors...")
        
        for monitor in monitors:
            original = monitor.original_url
            normalized = normalize_vinted_monitor_url(original)
            
            # Also check if params_json matches normalized parameters
            new_params = parse_vinted_url(normalized)
            try:
                current_params = json.loads(monitor.params_json)
                # Keep _original_interval if it exists
                if "_original_interval" in current_params:
                    new_params["_original_interval"] = current_params["_original_interval"]
            except Exception:
                current_params = {}

            params_changed = json.dumps(new_params, sort_keys=True) != json.dumps(current_params, sort_keys=True)
            
            if original != normalized or params_changed:
                dirty_count += 1
                if confirm:
                    logger.info(f"Fixed Monitor ID {monitor.id}: {original} -> {normalized}")
                    monitor.original_url = normalized
                    monitor.params_json = json.dumps(new_params)
                    fixed_count += 1
                else:
                    logger.info(f"Dry-run: Would fix Monitor ID {monitor.id}")
                    logger.info(f"  Old: {original}")
                    logger.info(f"  New: {normalized}")
                    if params_changed:
                        logger.info(f"  Params also changed.")

        if confirm:
            await db.commit()
            logger.info(f"Committed {fixed_count} updates.")
        else:
            logger.info(f"Dry-run complete. Found {dirty_count} monitors to fix. Use --confirm to apply changes.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Normalize existing monitor URLs and parameters.")
    parser.add_argument("--confirm", action="store_true", help="Actually write changes to the database.")
    args = parser.parse_args()
    
    asyncio.run(normalize_all_monitors(args.confirm))
