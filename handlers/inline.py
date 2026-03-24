from aiogram import Router, types
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
from sqlalchemy import select
from database.models import Anime
from database.engine import AsyncSessionLocal

inline_router = Router()

@inline_router.inline_query()
async def query_anime(query: types.InlineQuery):
    search_text = query.query.strip()
    
    # Agar qidiruv so'zi bo'lsa, bazadan qidiramiz
    async with AsyncSessionLocal() as session:
        if not search_text:
            # Bo'sh bo'lsa, eng oxirgi 10 ta animeni chiqaramiz
            sql = select(Anime).order_by(Anime.id.desc()).limit(10)
        else:
            # Nomi bo'yicha qidirish (Katta-kichik harfni farqlamaydi)
            sql = select(Anime).where(Anime.title.ilike(f"%{search_text}%")).limit(20)
        
        result = await session.execute(sql)
        animes = result.scalars().all()

    results = []
    for anime in animes:
        # Har bir anime uchun natija shakllantiramiz
        results.append(
            InlineQueryResultArticle(
                id=str(anime.id),
                title=anime.title,
                description=f"📅 Yil: {anime.year} | 🎭 Janr: {', '.join(anime.genres) if anime.genres else 'Noma`lum'}",
                thumbnail_url=None, # Poster file_id bo'lgani uchun bu yerda ko'rinmaydi
                input_message_content=InputTextMessageContent(
                    message_text=f"🎬 <b>{anime.title}</b>\n\nℹ️ <b>Ma'lumot:</b> {anime.description}\n📅 <b>Yili:</b> {anime.year}\n🌟 <b>Reyting:</b> {anime.rating}",
                    parse_mode="HTML"
                ),
                # Bu yerda "Tomosha qilish" tugmasini qo'shish mumkin
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="👁 Tomosha qilish", callback_data=f"view_{anime.id}")]
                ])
            )
        )

    await query.answer(results, cache_time=5)