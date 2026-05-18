# app/scheduler/tasks.py
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import FoundItem, HiddenSeller, Monitor, SeenItem, User
from app.scraper.client import VintedClient
from app.scraper.parser import VintedItem

logger = logging.getLogger(**name**)
settings = get_settings()

MAX_INTERVAL_SECONDS = 900
EMPTY_THRESHOLD_FAST = 5
EMPTY_THRESHOLD_SLOW = 15
INTERVAL_STEP_UP = 1.3
INTERVAL_STEP_DOWN_FAST = 0.7

_telegram_bot: Bot | None = None
_notification_lock = asyncio.Lock()

def set_telegram_bot(bot: Bot) -> None:
global _telegram_bot
_telegram_bot = bot

def _is_peak_time() -> bool:
hour = datetime.now(timezone.utc).hour
return settings.peak_start_hour <= hour < settings.peak_end_hour

def _get_effective_interval(base_interval: int) -> int:
if _is_peak_time():
return base_interval
hour = datetime.now(timezone.utc).hour
if 0 <= hour < settings.peak_start_hour:
return int(base_interval * settings.night_interval_multiplier)
return int(base_interval * settings.offpeak_interval_multiplier)

def _resolve_original_interval(monitor: Monitor) -> int:
try:
params: dict = json.loads(monitor.params_json)
return params.get("_original_interval", monitor.interval_sec)
except (json.JSONDecodeError, TypeError):
return monitor.interval_sec

async def _update_monitor_interval(db, monitor, found_new, count=0, original_interval=None):
if original_interval is None:
original_interval = _resolve_original_interval(monitor)

monitor.interval_sec = max(monitor.interval_sec, original_interval)

if found_new:
monitor.items_found_count += count
monitor.consecutive_empty = 0
new_interval = max(int(monitor.interval_sec * 0.7), original_interval)
monitor.interval_sec = new_interval
else:
monitor.consecutive_empty += 1
threshold = EMPTY_THRESHOLD_FAST if _is_peak_time() else EMPTY_THRESHOLD_SLOW
if monitor.consecutive_empty >= threshold:
new_interval = int(monitor.interval_sec * 1.3)
monitor.interval_sec = min(new_interval, MAX_INTERVAL_SECONDS)

async def check_monitor(monitor_id: int, client: VintedClient) -> None:
try:
async with AsyncSessionLocal() as db:
result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
monitor = result.scalar_one_or_none()
if monitor is None or not [monitor.is](https://monitor.is)_active:
return

params = json.loads(monitor.params_json)
domains = json.loads(monitor.domains_json)
user_id = monitor.user_id
is_cold_start = monitor.last_check_at is None or monitor.items_found_count == 0
original_interval = params.get("_original_interval", monitor.interval_sec)

hidden_result = await db.execute(select(HiddenSeller.seller_id))
hidden_seller_ids = {row[0] for row in hidden_result.fetchall()}

items = await client.search_all_domains(params, domains)

if not items:
async with AsyncSessionLocal() as db:
result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
monitor = result.scalar_one_or_none()
if monitor and [monitor.is](https://monitor.is)_active:
await _update_monitor_interval(db, monitor, False, original_interval=original_interval)
await db.commit()
return

async with AsyncSessionLocal() as db:
result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
monitor = result.scalar_one_or_none()
if monitor is None or not [monitor.is](https://monitor.is)_active:
return

filtered_items = [i for i in items if i.seller_id not in hidden_seller_ids]
new_items_to_notify = []

for item in filtered_items:
if [db.bind.dialect.name](https://db.bind.dialect.name) == 'postgresql':
stmt = pg_insert(SeenItem).values(
user_id=user_id, vinted_item_id=item.id, domain=item.domain,
seen_at=datetime.now(timezone.utc)
).on_conflict_do_nothing(index_elements=['user_id', 'vinted_item_id', 'domain'])
res = await db.execute(stmt)
is_new_for_user = res.rowcount > 0
else:
stmt = insert(SeenItem).values(
user_id=user_id, vinted_item_id=item.id, domain=item.domain,
seen_at=datetime.now(timezone.utc)
).prefix_with("OR IGNORE")
res = await db.execute(stmt)
is_new_for_user = res.rowcount > 0

notified_status = is_cold_start or not is_new_for_user

if [db.bind.dialect.name](https://db.bind.dialect.name) == 'postgresql':
found_stmt = pg_insert(FoundItem).values(
monitor_id=monitor_id, vinted_item_id=item.id, domain=item.domain,
title=item.title, price=item.price, currency=item.currency,
brand=item.brand, size=item.size, condition=item.condition,
photo_url=item.photo_url, item_url=item.item_url,
seller_id=item.seller_id, found_at=datetime.now(timezone.utc),
notified=notified_status
).on_conflict_do_nothing(index_elements=['monitor_id', 'vinted_item_id', 'domain'])
found_res = await db.execute(found_stmt)
if found_res.rowcount > 0 and not notified_status:
new_items_to_notify.append(item)
else:
found_stmt = insert(FoundItem).values(
monitor_id=monitor_id, vinted_item_id=item.id, domain=item.domain,
title=item.title, price=item.price, currency=item.currency,
brand=item.brand, size=item.size, condition=item.condition,
photo_url=item.photo_url, item_url=item.item_url,
seller_id=item.seller_id, found_at=datetime.now(timezone.utc),
notified=notified_status
).prefix_with("OR IGNORE")
found_res = await db.execute(found_stmt)
if found_res.rowcount > 0 and not notified_status:
new_items_to_notify.append(item)

await _update_monitor_interval(db, monitor, len(new_items_to_notify) > 0 or not is_cold_start,
count=len(new_items_to_notify), original_interval=original_interval)
monitor.last_check_at = datetime.now(timezone.utc)
await db.commit()

if new_items_to_notify:
asyncio.create_task(process_pending_notifications())
except Exception as e:
logger.error(f"Error in check_monitor {monitor_id}: {e}")
raise

async def process_pending_notifications() -> None:
async with _notification_lock:
async with AsyncSessionLocal() as db:
query = select(FoundItem).where(FoundItem.notified == False).order_by(FoundItem.found_at.asc()).limit(50)

if [db.bind.dialect.name](https://db.bind.dialect.name) == 'postgresql':
query = query.with_for_update(skip_locked=True)

result = await db.execute(query)
pending_items = result.scalars().all()

if not pending_items:
return

for fi in pending_items:
item = VintedItem(
id=fi.vinted_item_id, title=fi.title, price=fi.price, currency=fi.currency,
brand=fi.brand, size=fi.size, condition=fi.condition, photo_url=fi.photo_url,
item_url=fi.item_url, domain=fi.domain, seller_id=fi.seller_id
)

bot_to_use = _telegram_bot
chat_id_to_use = settings.telegram_chat_id

async with AsyncSessionLocal() as db2:
monitor = await db2.get(Monitor, fi.monitor_id)
if monitor and monitor.user_id:
user = await db2.get(User, monitor.user_id)
if user and user.telegram_bot_token and user.telegram_chat_id:
from app.telegram.bot import get_or_create_bot
bot_to_use, _ = get_or_create_bot(user.telegram_bot_token)
chat_id_to_use = int(user.telegram_chat_id)

if bot_to_use and chat_id_to_use:
try:
from app.telegram.notifications import send_item_notification
await send_item_notification(bot_to_use, chat_id_to_use, item)
fi.notified = True
await db.commit()
except Exception:
break

class MonitorScheduler:
def **init**(self, client: VintedClient) -> None:
self.client = client
self.scheduler = AsyncIOScheduler()
self.job_ids: dict[int, str] = {}

async def start(self) -> None:
async with AsyncSessionLocal() as db:
result = await db.execute(select(Monitor).where([Monitor.is](https://Monitor.is)_active == True))
monitors = result.scalars().all()

for monitor in monitors:
effective = *get_effective_interval(monitor.interval_sec)
stagger = random.uniform(5.0, 30.0)
job = self.scheduler.add_job(
check_monitor, trigger=IntervalTrigger(seconds=effective),
args=[monitor.id, self.client], id=f"monitor*{monitor.id}",
next_run_time=datetime.now(timezone.utc) + timedelta(seconds=stagger)
)
if job:
self.job_ids[monitor.id] = job.id

self.scheduler.start()
[logger.info](https://logger.info)("Scheduler started with %d monitors", len(monitors))

async def stop(self) -> None:
self.scheduler.shutdown(wait=True)

def add_monitor(self, monitor_id: int, interval_sec: int) -> None:
effective = *get_effective_interval(interval_sec)
job = self.scheduler.add_job(
check_monitor, trigger=IntervalTrigger(seconds=effective),
args=[monitor_id, self.client], id=f"monitor*{monitor_id}"
)
if job:
self.job_ids[monitor_id] = job.id

def remove_monitor(self, monitor_id: int) -> None:
job_id = self.job_ids.pop(monitor_id, None)
if job_id:
self.scheduler.remove_job(job_id)

def update_monitor(self, monitor_id: int, interval_sec: int) -> None:
self.remove_monitor(monitor_id)
self.add_monitor(monitor_id, interval_sec)