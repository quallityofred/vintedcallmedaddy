import asyncio
import time
import logging
from typing import Dict

logger = logging.getLogger(__name__)

class TelegramRateLimiter:
    def __init__(self, global_rate: float = 25.0, private_chat_rate: float = 1.0, group_chat_rate: float = 0.33):
        # global_rate: messages per second (25/sec)
        # private_chat_rate: messages per second (1/sec)
        # group_chat_rate: messages per second (20/min = 0.33/sec)
        self.global_semaphore = asyncio.Semaphore(int(global_rate))
        self.chat_limiters: Dict[int, asyncio.Semaphore] = {}
        self.private_chat_rate = private_chat_rate
        self.group_chat_rate = group_chat_rate
        self.last_global_reset = time.monotonic()

    async def acquire(self, chat_id: int, is_group: bool = False):
        # Global limit
        await self.global_semaphore.acquire()
        asyncio.create_task(self._release_after(self.global_semaphore, 1.0))

        # Per-chat limit
        rate = self.group_chat_rate if is_group else self.private_chat_rate
        if chat_id not in self.chat_limiters:
            self.chat_limiters[chat_id] = asyncio.Semaphore(1)

        await self.chat_limiters[chat_id].acquire()
        asyncio.create_task(self._release_after(self.chat_limiters[chat_id], 1.0 / rate))

    async def _release_after(self, semaphore: asyncio.Semaphore, delay: float):
        await asyncio.sleep(delay)
        semaphore.release()
