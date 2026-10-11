"""
inline.py — inline qidiruv.

Inline tanlanganda:
  - Foydalanuvchi chatda https://t.me/bot?start=anime_ID linkini yuboradi
  - Bot shu linkni ko'rib kontent kartasini chiqaradi (users.py da)

Qidiruv:
  - Bo'sh → Top 18 (9 ko'p ko'rilgan + 9 yuqori reyting)
  - Matn → shu nomdagi kontentlar
  - Natijalar tepasida: «● 93 kishi online • ✦ 975 ta kontent mavjud» — bosilsa oddiy /start

Filtr:
  - Oddiy user: pro_locked kontent ko'rinmaydi
  - Pro user: hammasi ko'rinadi

Rasm: kontentning o'z inline rasmi bo'lmasa — admin belgilagan standart rasm
(BotSetting `inline_default_thumb`, yoki DEFAULT_INLINE_THUMB muhit o'zgaruvchisi).
Ikkisi ham bo'lmasa — rasm ko'rsatilmaydi (buzuq/bloklangan havolaga urinilmaydi).
"""

import os
import time
from datetime import datetime

from aiogram import Router, types
from aiogram.types import (
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputTextMessageContent,
)
from sqlalchemy import select

from database.engine import AsyncSessionLocal
from database.models import Anime, BotSetting, User
from utils.live_stats import get_live_stats
from utils.ui import anime_start_link

inline_router = Router()

BOT_USERNAME = os.getenv("BOT_USERNAME", "kaworai_uz_bot")
DEFAULT_THUMB_KEY = "inline_default_thumb"
HOME_START_PARAM = "home"  # /start home → shunchaki bosh menyu (users.py da hech narsa qilmaydi)

_default_cache: dict = {"t": 0.0, "v": None}
_DEFAULT_TTL = 60.0


def reset_default_thumb_cache() -> None:
    """Admin standart rasmni o'zgartirganda darrov yangilanishi uchun."""
    _default_cache["t"] = 0.0


async def get_default_thumb() -> str | None:
    now = time.monotonic()
    if _default_cache["t"] and now - _default_cache["t"] < _DEFAULT_TTL:
        return _default_cache["v"]
    value = None
    try:
        async with AsyncSessionLocal() as session:
            row = (await session.execute(select(BotSetting).where(BotSetting.key == DEFAULT_THUMB_KEY))).scalar_one_or_none()
            value = row.value if row and row.value else None
    except Exception:
        value = _default_cache["v"]
    value = value or os.getenv("DEFAULT_INLINE_THUMB") or None
    _default_cache.update(t=now, v=value)
    return value


async def _is_pro(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.is_pro:
            return False
        if user.pro_until and user.pro_until < datetime.utcnow():
            user.is_pro = False
            user.pro_until = None
            await session.commit()
            return False
        return True


def _make_result(anime: Anime, default_thumb: str | None) -> InlineQueryResultArticle:
    """
    Inline natija — tanlanganda foydalanuvchi chatda
    https://t.me/BOT?start=anime_ID linkini yuboradi.
    """
    lock = "⊘ " if getattr(anime, "is_pro_locked", False) else ""
    eps = getattr(anime, "episodes_count", None) or anime.total_episodes or "?"
    genres = " • ".join((anime.genres or [])[:4]) or "—"
    desc = f"{lock}★ {float(anime.rating or 0):.1f}  •  ᐅ {eps} qism  •  ◎ {anime.year or '—'}\n{genres}"

    kwargs = {}
    thumb = anime.inline_thumbnail_url or default_thumb
    if thumb:
        kwargs["thumbnail_url"] = thumb

    return InlineQueryResultArticle(
        id=str(anime.id),
        title=f"๏ {anime.title}",
        description=desc,
        input_message_content=InputTextMessageContent(message_text=anime_start_link(anime.id)),
        **kwargs,
    )


async def _header_button() -> InlineQueryResultsButton:
    online, total = await get_live_stats()
    return InlineQueryResultsButton(
        text=f"● {max(online, 1)} kishi online  •  ✦ {total} ta kontent mavjud",
        start_parameter=HOME_START_PARAM,
    )


@inline_router.inline_query()
async def query_anime(query: types.InlineQuery):
    search_text = query.query.strip()
    is_pro = await _is_pro(query.from_user.id)

    async with AsyncSessionLocal() as session:
        if not search_text:
            top_views = (await session.execute(select(Anime).order_by(Anime.views.desc()).limit(9))).scalars().all()
            top_rated = (
                (
                    await session.execute(
                        select(Anime).where(Anime.rating_count >= 1).order_by(Anime.rating.desc()).limit(9)
                    )
                )
                .scalars()
                .all()
            )
            seen, animes = set(), []
            for a in list(top_views) + list(top_rated):
                if a.id not in seen:
                    seen.add(a.id)
                    animes.append(a)
        else:
            result = await session.execute(select(Anime).where(Anime.title.ilike(f"%{search_text}%")).limit(30))
            animes = result.scalars().all()

    default_thumb = await get_default_thumb()
    results = [
        _make_result(a, default_thumb) for a in animes if is_pro or not getattr(a, "is_pro_locked", False)
    ]

    await query.answer(results, cache_time=5, is_personal=True, button=await _header_button())
