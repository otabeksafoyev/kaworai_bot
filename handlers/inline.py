from aiogram import Router, types
from aiogram.types import (
    InlineQueryResultArticle,
    InlineQueryResultPhoto,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from sqlalchemy import select
from database.models import Anime
from database.engine import AsyncSessionLocal

inline_router = Router()

DEFAULT_THUMB = "https://i.imgur.com/JyOSMOR.png"  # Rasm yo'q bo'lsa


@inline_router.inline_query()
async def query_anime(query: types.InlineQuery):
    search_text = query.query.strip()

    async with AsyncSessionLocal() as session:
        if not search_text:
            sql = select(Anime).order_by(Anime.id.desc()).limit(10)
        else:
            sql = select(Anime).where(
                Anime.title.ilike(f"%{search_text}%")
            ).limit(20)

        result = await session.execute(sql)
        animes = result.scalars().all()

    results = []
    for anime in animes:
        genres_text = ", ".join(anime.genres) if anime.genres else "Nomalum"

        # Inline bosilganda botga o'tish tugmasi
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="▶️ Tomosha qilish",
                url=f"https://t.me/kaworai_uz_bot?start=anime_{anime.id}"
            )]
        ])

        message_text = (
            f"🎬 <b>{anime.title}</b>\n\n"
            f"📅 Yil: {anime.year}\n"
            f"🎭 Janr: {genres_text}\n"
            f"⭐ Reyting: {anime.rating} ({anime.rating_count} ovoz)\n\n"
            f"📖 {anime.description}"
        )

        thumb = anime.inline_thumbnail_url or DEFAULT_THUMB

        # inline_thumbnail_url bor bo'lsa — rasmli natija
        if anime.inline_thumbnail_url:
            results.append(
                InlineQueryResultPhoto(
                    id=str(anime.id),
                    photo_url=anime.inline_thumbnail_url,
                    thumbnail_url=anime.inline_thumbnail_url,
                    title=anime.title,
                    description=f"⭐ {anime.rating} | 📅 {anime.year} | 🎭 {genres_text}",
                    caption=message_text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            )
        else:
            # URL yo'q — matnsiz natija
            results.append(
                InlineQueryResultArticle(
                    id=str(anime.id),
                    title=f"🎬 {anime.title}",
                    description=f"⭐ {anime.rating} | 📅 {anime.year} | 🎭 {genres_text}",
                    thumbnail_url=DEFAULT_THUMB,
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                        parse_mode="HTML"
                    ),
                    reply_markup=kb
                )
            )

    await query.answer(results, cache_time=5, is_personal=True)