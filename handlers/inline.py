from aiogram import Router, types
from aiogram.types import (
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from sqlalchemy import select
from database.models import Anime, User
from database.engine import AsyncSessionLocal

inline_router = Router()

DEFAULT_THUMB = "https://i.imgur.com/JyOSMOR.png"


async def _is_pro(user_id: int) -> bool:
    from datetime import datetime
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


@inline_router.inline_query()
async def query_anime(query: types.InlineQuery):
    search_text = query.query.strip()
    user_id     = query.from_user.id
    is_pro      = await _is_pro(user_id)

    async with AsyncSessionLocal() as session:
        if not search_text:
            sql = select(Anime).order_by(Anime.id.desc()).limit(20)
        else:
            sql = (
                select(Anime)
                .where(Anime.title.ilike(f"%{search_text}%"))
                .limit(30)
            )
        result = await session.execute(sql)
        all_animes = result.scalars().all()

    animes = [a for a in all_animes if is_pro or not a.is_pro_locked]

    results = []
    for anime in animes:
        genres_text = ", ".join(anime.genres or []) or "Nomalum"
        ep_text     = str(anime.episodes_count or anime.total_episodes or "?")
        thumb       = anime.inline_thumbnail_url or DEFAULT_THUMB

        results.append(
            InlineQueryResultArticle(
                id=str(anime.id),
                title=f"🎬 {anime.title}",
                description=(
                    f"⭐ {anime.rating:.1f} | "
                    f"📅 {anime.year or '—'} | "
                    f"🎭 {genres_text[:30]} | "
                    f"📺 {ep_text} qism"
                ),
                thumbnail_url=thumb,
                input_message_content=InputTextMessageContent(
                    message_text=f"anime_{anime.id}",
                ),
            )
        )

    await query.answer(results, cache_time=5, is_personal=True)