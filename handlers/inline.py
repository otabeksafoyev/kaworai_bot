"""
inline.py — to'liq tuzatilgan

- Inline tanlanganda: https://t.me/bot?start=anime_ID LINK yuboriladi (matn emas)
- Bo'sh qidiruv → Top 18 (9 ko'p ko'rilgan + 9 yuqori reyting)
- Oddiy user: pro_locked va is_hidden animelar chiqmaydi
- Pro user: hammasi chiqadi
"""

from aiogram import Router, types
from aiogram.types import (
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from sqlalchemy import select
from database.models import Anime, User
from database.engine import AsyncSessionLocal
from datetime import datetime
import os

inline_router = Router()

BOT_USERNAME  = os.getenv("BOT_USERNAME", "kaworai_uz_bot")
DEFAULT_THUMB = "https://i.imgur.com/JyOSMOR.png"


async def _is_pro(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.is_pro:
            return False
        if user.pro_until and user.pro_until < datetime.utcnow():
            user.is_pro    = False
            user.pro_until = None
            await session.commit()
            return False
        return True


def _make_share_url(anime_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=anime_{anime_id}"


def _build_result(anime: Anime, is_pro: bool) -> InlineQueryResultArticle:
    genres_text = ", ".join((anime.genres or [])[:3]) or "Nomalum"
    ep_text     = str(anime.episodes_count or anime.total_episodes or "?")
    thumb       = anime.inline_thumbnail_url or DEFAULT_THUMB
    share_url   = _make_share_url(anime.id)

    lock_icon = "🔒 " if anime.is_pro_locked else ""
    desc = (
        f"{lock_icon}⭐ {anime.rating:.1f} | "
        f"📅 {anime.year or '—'} | "
        f"🎭 {genres_text[:30]} | "
        f"📺 {ep_text} qism"
    )

    # Inline tanlanganda faqat https link yuboriladi
    # users.py dagi handle_text bu linkni ushlaydi va anime kartasini ko'rsatadi
    return InlineQueryResultArticle(
        id=str(anime.id),
        title=f"🎬 {lock_icon}{anime.title}",
        description=desc,
        thumbnail_url=thumb,
        input_message_content=InputTextMessageContent(
            message_text=share_url,
        ),
    )


@inline_router.inline_query()
async def query_anime(query: types.InlineQuery):
    search_text = query.query.strip()
    user_id     = query.from_user.id
    is_pro      = await _is_pro(user_id)

    async with AsyncSessionLocal() as session:
        if not search_text:
            # Bo'sh qidiruv → Top 18: 9 ko'p ko'rilgan + 9 yuqori reyting
            top_views = (await session.execute(
                select(Anime).order_by(Anime.views.desc()).limit(9)
            )).scalars().all()

            top_rated = (await session.execute(
                select(Anime)
                .where(Anime.rating_count >= 1)
                .order_by(Anime.rating.desc())
                .limit(9)
            )).scalars().all()

            seen   = set()
            animes = []
            for a in list(top_views) + list(top_rated):
                if a.id not in seen:
                    seen.add(a.id)
                    animes.append(a)
        else:
            result = await session.execute(
                select(Anime).where(Anime.title.ilike(f"%{search_text}%")).limit(30)
            )
            animes = result.scalars().all()

    results = []
    for anime in animes:
        if not is_pro and anime.is_pro_locked:
            continue
        if getattr(anime, "is_hidden", False):
            continue
        results.append(_build_result(anime, is_pro))

    await query.answer(results, cache_time=5, is_personal=True)