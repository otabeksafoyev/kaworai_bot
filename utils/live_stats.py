"""
utils/live_stats.py — bosh menyu va inline qidiruv tepasi uchun jonli raqamlar:
hozir onlayn foydalanuvchilar (so'nggi 5 daqiqada faol) va jami kontent soni.
Har inline so'rov (har harf!) bazaga yuk bo'lmasligi uchun 30 soniya keshlanadi.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select

from database.engine import AsyncSessionLocal
from database.models import Anime, User

logger = logging.getLogger(__name__)

ONLINE_WINDOW_MIN = 5
CACHE_TTL = 30.0
_cache: dict = {"t": 0.0, "online": 0, "total": 0}


async def get_live_stats() -> tuple[int, int]:
    """(onlayn foydalanuvchilar, jami kontent). Xato bo'lsa — oxirgi ma'lum qiymat."""
    now = time.monotonic()
    if _cache["t"] and now - _cache["t"] < CACHE_TTL:
        return _cache["online"], _cache["total"]
    try:
        since = datetime.utcnow() - timedelta(minutes=ONLINE_WINDOW_MIN)
        async with AsyncSessionLocal() as session:
            online = (
                await session.execute(select(func.count(User.telegram_id)).where(User.last_active >= since))
            ).scalar() or 0
            total = (await session.execute(select(func.count(Anime.id)))).scalar() or 0
        _cache.update(t=now, online=int(online), total=int(total))
    except Exception:
        logger.warning("live_stats xato", exc_info=True)
    return _cache["online"], _cache["total"]
