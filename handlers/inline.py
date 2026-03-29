from aiogram import Router, types
from aiogram.types import (
    InlineQueryResultArticle,
    InlineQueryResultVideo,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from sqlalchemy import select
from database.models import Anime, Series
from database.engine import AsyncSessionLocal

inline_router = Router()

BOT_USERNAME = "kaworai_uz_bot"  # ✅ bot username sini shu yerda o'zgartiring
DEFAULT_THUMB = "https://i.imgur.com/JyOSMOR.png"


@inline_router.inline_query()
async def query_anime(query: types.InlineQuery):
    search_text = query.query.strip()

    async with AsyncSessionLocal() as session:
        if not search_text:
            sql = select(Anime).order_by(Anime.id.desc()).limit(10)
        else:
            sql = select(Anime).where(Anime.title.ilike(f"%{search_text}%")).limit(20)

        result = await session.execute(sql)
        animes = result.scalars().all()

        # Har bir anime uchun 1-qismni ham olish
        anime_first_eps = {}
        for anime in animes:
            ep_result = await session.execute(
                select(Series)
                .where(Series.anime_id == anime.id)
                .order_by(Series.episode.asc())
                .limit(1)
            )
            first_ep = ep_result.scalar_one_or_none()
            anime_first_eps[anime.id] = first_ep

    results = []

    for anime in animes:
        genres_text = ", ".join(anime.genres) if anime.genres else "Nomalum"
        total_ep_text = str(anime.total_episodes) if anime.total_episodes else "?"
        first_ep = anime_first_eps.get(anime.id)

        # ✅ Inline bosilganda botga o'tish — ?start=anime_ID
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="▶️ Tomosha qilish",
                url=f"https://t.me/{BOT_USERNAME}?start=anime_{anime.id}"
            )
        ]])

        message_text = (
            f"🎬 <b>{anime.title}</b>\n\n"
            f"📅 Yil: {anime.year}\n"
            f"🎭 Janr: {genres_text}\n"
            f"⭐ Reyting: {anime.rating} ({anime.rating_count} ovoz)\n"
            f"📺 Seriyalar: {total_ep_text}\n\n"
            f"📖 {anime.description}"
        )

        # ✅ TUZATILDI: agar inline_thumbnail_url bor bo'lsa — FAQAT o'shani ishlatamiz
        # InlineQueryResultVideo ishlatamiz — bu 1 ta rasm chiqaradi, 2 ta emas
        if anime.inline_thumbnail_url:
            results.append(
                InlineQueryResultArticle(
                    id=str(anime.id),
                    title=f"🎬 {anime.title}",
                    description=f"⭐ {anime.rating} | 📅 {anime.year} | 🎭 {genres_text} | 📺 {total_ep_text} qism",
                    thumbnail_url=anime.inline_thumbnail_url,  # ✅ faqat admin qo'shgan rasm
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                        parse_mode="HTML"
                    ),
                    reply_markup=kb
                )
            )
        else:
            # URL yo'q — default rasm bilan
            results.append(
                InlineQueryResultArticle(
                    id=str(anime.id),
                    title=f"🎬 {anime.title}",
                    description=f"⭐ {anime.rating} | 📅 {anime.year} | 🎭 {genres_text} | 📺 {total_ep_text} qism",
                    thumbnail_url=DEFAULT_THUMB,
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                        parse_mode="HTML"
                    ),
                    reply_markup=kb
                )
            )

    await query.answer(results, cache_time=5, is_personal=True)