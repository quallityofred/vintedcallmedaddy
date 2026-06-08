from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramRetryAfter

from app.scraper.parser import VintedItem
from app.telegram.notifications import send_item_notification
from app.telegram.rate_limiter import TelegramRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_item(*, photo_url: str = "https://images.example.invalid/item.jpg") -> VintedItem:
    return VintedItem(
        id=1,
        title="Item",
        price=10,
        currency="EUR",
        brand="Brand",
        size="M",
        condition="new",
        photo_url=photo_url,
        item_url="https://www.vinted.pl/items/1",
        domain="vinted.pl",
        seller_id=1,
    )


@pytest.mark.asyncio
async def test_private_unknown_chat_limit_is_one_per_second():
    clock = FakeClock()
    limiter = TelegramRateLimiter(clock=clock, sleep=clock.sleep)

    await limiter.acquire(123)
    await limiter.acquire(123)

    assert clock.sleeps == [1.0]


@pytest.mark.asyncio
async def test_group_chat_limit_is_twenty_per_minute():
    clock = FakeClock()
    limiter = TelegramRateLimiter(clock=clock, sleep=clock.sleep)

    await limiter.acquire(-100, is_group=True)
    await limiter.acquire(-100, is_group=True)

    assert clock.sleeps == [3.0]


@pytest.mark.asyncio
async def test_global_limit_is_twenty_five_per_second():
    clock = FakeClock()
    limiter = TelegramRateLimiter(clock=clock, sleep=clock.sleep)

    for chat_id in range(26):
        await limiter.acquire(chat_id)

    assert 1.0 in clock.sleeps


@pytest.mark.asyncio
async def test_photo_and_fallback_text_are_both_rate_limited():
    bot = MagicMock()
    bot.send_photo = AsyncMock(side_effect=RuntimeError("bad photo"))
    bot.send_message = AsyncMock()
    limiter = MagicMock()
    limiter.acquire = AsyncMock()

    with patch("app.telegram.notifications.rate_limiter", limiter):
        result = await send_item_notification(bot, 123, make_item())

    assert result == "fallback_text"
    assert limiter.acquire.await_count == 2
    bot.send_photo.assert_awaited_once()
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_text_only_send_is_rate_limited():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    limiter = MagicMock()
    limiter.acquire = AsyncMock()

    with patch("app.telegram.notifications.rate_limiter", limiter):
        result = await send_item_notification(bot, 123, make_item(photo_url=""))

    assert result == "text"
    limiter.acquire.assert_awaited_once_with(123, is_group=False)


@pytest.mark.asyncio
async def test_retry_after_is_respected_and_raised_after_retries():
    retry_error = TelegramRetryAfter(
        method=MagicMock(),
        message="rate limited",
        retry_after=4,
    )
    bot = MagicMock()
    bot.send_photo = AsyncMock(side_effect=retry_error)
    limiter = MagicMock()
    limiter.acquire = AsyncMock()
    sleep_mock = AsyncMock()

    with patch("app.telegram.notifications.rate_limiter", limiter), patch(
        "app.telegram.notifications.asyncio.sleep", sleep_mock
    ):
        with pytest.raises(TelegramRetryAfter):
            await send_item_notification(bot, 123, make_item())

    assert bot.send_photo.await_count == 3
    assert limiter.acquire.await_count == 3
    assert sleep_mock.await_count == 3
    assert all(call.args == (4,) for call in sleep_mock.await_args_list)
    bot.send_message.assert_not_called()
