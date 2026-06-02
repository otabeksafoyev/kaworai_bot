"""
utils/helpers.py — Watch state yordamchilari

Redis mavjud bo'lsa Redis, aks holda MemoryStorage (dict) ishlatadi.
Modulni yuklashda ulanish qilmaydi — xato bo'lmaydi.
"""

import time
from typing import Any

# In-memory fallback — Redis bo'lmasa
_memory_store: dict[str, dict] = {}


async def _get_redis():
    """Redis klientini qaytaradi. Mavjud bo'lmasa None."""
    try:
        from utils.redis_pro import get_redis
        return await get_redis()
    except Exception:
        return None


async def set_watching(user_id: int, anime_id: int, episode: int = 1) -> None:
    """Foydalanuvchi hozir qaysi animeni ko'rayotganini saqlaydi."""
    data = {"anime_id": str(anime_id), "episode": str(episode), "timestamp": str(int(time.time()))}
    r = await _get_redis()
    if r:
        try:
            await r.hset(f"watch:{user_id}", mapping=data)
            await r.expire(f"watch:{user_id}", 86400)  # 24 soat
            return
        except Exception:
            pass
    # Redis yo'q — xotiraga saqlaymiz
    _memory_store[f"watch:{user_id}"] = data


async def get_watching(user_id: int) -> dict[str, Any] | None:
    """Foydalanuvchi hozir ko'rayotgan anime ma'lumotini qaytaradi."""
    r = await _get_redis()
    if r:
        try:
            data = await r.hgetall(f"watch:{user_id}")
            if data:
                return data
        except Exception:
            pass
    # Xotiradan
    return _memory_store.get(f"watch:{user_id}")


async def clear_watching(user_id: int) -> None:
    """Watch holatini tozalaydi."""
    r = await _get_redis()
    if r:
        try:
            await r.delete(f"watch:{user_id}")
        except Exception:
            pass
    _memory_store.pop(f"watch:{user_id}", None)
