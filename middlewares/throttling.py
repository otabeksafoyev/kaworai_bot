# middlewares/throttling.py
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Dict, Any, Awaitable
from cachetools import TTLCache
import time

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate: float = 0.7):
        self.rate = rate
        self.cache = TTLCache(maxsize=10_000, ttl=300)  # 5 daqiqa xotira

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        key = f"throttle_{user.id}"
        now = time.time()

        if key in self.cache and now - self.cache[key] < self.rate:
            # Bu yerda xohlasangiz javob yuborishingiz mumkin, yoki shunchaki o'tkazib yuborish
            return

        self.cache[key] = now
        return await handler(event, data)