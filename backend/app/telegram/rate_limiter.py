import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

class TelegramRateLimiter:
    def __init__(
        self,
        global_rate: float = 25.0,
        private_chat_rate: float = 1.0,
        group_chat_rate: float = 20.0 / 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.global_rate = max(global_rate, 1.0)
        self.private_chat_rate = private_chat_rate
        self.group_chat_rate = group_chat_rate
        self._clock = clock
        self._sleep = sleep
        self._global_lock = asyncio.Lock()
        self._global_attempts: deque[float] = deque()
        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._chat_next_allowed: dict[int, float] = {}

    async def acquire(self, chat_id: int, is_group: bool = False) -> None:
        await self._acquire_global_slot()

        chat_lock = self._chat_locks.setdefault(chat_id, asyncio.Lock())
        async with chat_lock:
            rate = self.group_chat_rate if is_group else self.private_chat_rate
            interval = 1.0 / max(rate, 0.001)
            now = self._clock()
            wait_seconds = max(0.0, self._chat_next_allowed.get(chat_id, now) - now)
            if wait_seconds:
                await self._sleep(wait_seconds)
            self._chat_next_allowed[chat_id] = self._clock() + interval

    async def _acquire_global_slot(self) -> None:
        capacity = max(1, int(self.global_rate))
        async with self._global_lock:
            while True:
                now = self._clock()
                cutoff = now - 1.0
                while self._global_attempts and self._global_attempts[0] <= cutoff:
                    self._global_attempts.popleft()
                if len(self._global_attempts) < capacity:
                    self._global_attempts.append(now)
                    return
                await self._sleep(max(0.0, self._global_attempts[0] + 1.0 - now))
