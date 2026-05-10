# scripts/fix_urls.py
import asyncio
import json
import logging
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Monitor
from app.scraper.url_parser import parse_vinted_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fix_monitor_urls():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Monitor))
        monitors = result.scalars().all()
        
        updated_count = 0
        for monitor in monitors:
            logger.info(f"Processing monitor: {monitor.name}")
            try:
                # Use the new robust parser to re-parse the original URL
                parsed = parse_vinted_url(monitor.original_url)
                
                new_params_json = json.dumps(parsed["params"])
                
                if monitor.params_json != new_params_json:
                    logger.info(f"Updating params for {monitor.name}")
                    logger.info(f"Old: {monitor.params_json}")
                    logger.info(f"New: {new_params_json}")
                    monitor.params_json = new_params_json
                    updated_count += 1
            except Exception as e:
                logger.error(f"Failed to fix URL for {monitor.name}: {e}")
        
        if updated_count > 0:
            await db.commit()
            logger.info(f"Successfully updated {updated_count} monitors.")
        else:
            logger.info("No monitors needed updates.")

if __name__ == "__main__":
    asyncio.run(fix_monitor_urls())
