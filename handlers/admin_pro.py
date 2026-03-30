"""
Kaworai Pro — Admin JSON Import Handler
Mavjud admin.py ga QO'SHILADI (almashtirmaydi).

Qo'shish kerak bo'lgan yangi handlerlar:
  1. JSON orqali kontent qo'shish (admin yozgan JSON ni parse qiladi)
  2. Pro-lock toggle
  3. Popularity recalculate
  4. Admin statistika (Pro)

FOYDALANISH:
  admin.py ga quyidagi import va router ni qo'shing:
  from handlers.admin_pro import pro_admin_router
  dp.include_router(pro_admin_router)
"""

import json
import asyncio
from aiogram import Router, F, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func

from database.models import Anime, RelatedContent, Admin
from database.engine import AsyncSessionLocal
from utils.recommendation import recalculate_popularity, _anime_to_dict
import os

pro_admin_router = Router()
ADMINS = os.getenv("ADMIN_ID", "").split(",")


# ─── Admin tekshirish (mavjud funksiya bilan bir xil) ───
async def is_admin(user_id: int) -> bool:
    if str(user_id) in ADMINS:
        return True
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Admin).where(Admin.telegram_id == user_id)
        )
        return result.scalar_one_or_none() is not None


# ═══════════════════════════════════════════════════════════
#  JSON IMPORT — ASOSIY FUNKSIYA
# ═══════════════════════════════════════════════════════════

EXPECTED_JSON_FORMAT = """{
  "id": 4345,
  "title": "Attack on Titan",
  "type": "anime",
  "year": 2013,
  "genres": ["action", "drama", "fantasy"],
  "tags": ["dark", "survival", "revenge"],
  "mood": ["dark", "emotional"],
  "rating": 9.0,
  "episodes": 25,
  "duration": 24,
  "status": "completed",
  "description": "Humanity fights against giants...",
  "poster_url": "https://...",
  "trailer_url": "https://...",
  "related": [
    { "id": 5001, "type": "sequel" },
    { "id": 5002, "type": "spin-off" }
  ],
  "popularity": 8.7,
  "is_pro_locked": false
}"""


@pro_admin_router.message(Command("json_add"))
async def json_add_command(msg: Message):
    """
    /json_add buyrug'i bilan JSON formatini ko'rsatadi.
    Admin keyin JSON ni xabar sifatida yuboradi.
    """
    if not await is_admin(msg.from_user.id):
        return

    await msg.answer(
        "📥 <b>JSON orqali kontent qo'shish</b>\n\n"
        "Quyidagi formatda JSON yuboring:\n\n"
        f"<pre>{EXPECTED_JSON_FORMAT}</pre>\n\n"
        "📌 <b>Eslatmalar:</b>\n"
        "• <code>type</code>: anime | movie | serial | dorama\n"
        "• <code>status</code>: ongoing | completed | announced\n"
        "• <code>is_pro_locked</code>: true | false (ixtiyoriy)\n"
        "• <code>related</code>: ixtiyoriy\n"
        "• <code>poster_url</code> va <code>trailer_url</code>: URL yoki mavjud file_id\n\n"
        "✉️ JSON ni keyingi xabarda yuboring.",
        parse_mode="HTML"
    )

    # Keyingi xabar JSON bo'lishini kutish uchun state saqlamaymiz,
    # chunki /json_import_data handler bor.


@pro_admin_router.message(Command("json_import_data"))
async def json_import_trigger(msg: Message):
    """
    Hint: /json_add dan keyin JSON yuborganda bu handler ishlamaydi.
    Buning o'rniga raw JSON text handler ishlatiladi.
    """
    pass


@pro_admin_router.message(F.text & F.text.startswith("{"))
async def handle_json_import(msg: Message):
    """
    Admin { bilan boshlangan xabar yuborganida — JSON import deb qabul qiladi.
    """
    if not await is_admin(msg.from_user.id):
        return

    processing = await msg.answer("⏳ JSON tahlil qilinmoqda...")

    try:
        data = json.loads(msg.text.strip())
    except json.JSONDecodeError as e:
        await processing.delete()
        return await msg.answer(
            f"❌ <b>JSON xato!</b>\n\n"
            f"<code>{str(e)}</code>\n\n"
            f"JSON validator: https://jsonlint.com",
            parse_mode="HTML"
        )

    # Majburiy maydonlar tekshirish
    required = ["id", "title"]
    missing = [f for f in required if f not in data]
    if missing:
        await processing.delete()
        return await msg.answer(
            f"❌ Majburiy maydonlar yo'q: <code>{', '.join(missing)}</code>",
            parse_mode="HTML"
        )

    anime_id = data.get("id")
    if not isinstance(anime_id, int):
        await processing.delete()
        return await msg.answer("❌ <code>id</code> butun son bo'lishi kerak!", parse_mode="HTML")

    async with AsyncSessionLocal() as session:
        # ID mavjudligini tekshirish
        existing = await session.get(Anime, anime_id)
        if existing:
            await processing.delete()

            # Yangilash taklifi
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ Yangilash",
                        callback_data=f"json_update_{anime_id}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Bekor qilish",
                        callback_data="json_cancel"
                    )
                ]
            ])
            return await msg.answer(
                f"⚠️ <b>ID {anime_id}</b> allaqachon mavjud!\n\n"
                f"Mavjud: <b>{existing.title}</b>\n\n"
                f"Yangilamoqchimisiz?",
                reply_markup=kb,
                parse_mode="HTML"
            )

        # Yangi kontent yaratish
        new_anime = _build_anime_from_json(data)
        session.add(new_anime)
        await session.flush()   # ID olish uchun

        # Related content qo'shish
        related_list = data.get("related", [])
        related_errors = []
        for rel in related_list:
            rel_id   = rel.get("id")
            rel_type = rel.get("type", "similar")
            if not rel_id:
                continue
            rel_anime = await session.get(Anime, rel_id)
            if not rel_anime:
                related_errors.append(rel_id)
                continue
            rc = RelatedContent(
                anime_id=anime_id,
                related_id=rel_id,
                relation_type=rel_type
            )
            session.add(rc)

        await session.commit()

        # Popularity hisoblash
        await recalculate_popularity(session, anime_id)

    await processing.delete()

    # Preview
    genres_str = ", ".join(data.get("genres", [])) or "—"
    tags_str   = ", ".join(data.get("tags",   [])) or "—"
    mood_str   = ", ".join(data.get("mood",   [])) or "—"
    related_str = f"{len(related_list)} ta" if related_list else "Yo'q"
    err_str    = f"\n⚠️ Topilmagan related IDs: {related_errors}" if related_errors else ""

    success_text = (
        f"✅ <b>{data.get('title')}</b> qo'shildi!\n\n"
        f"🆔 ID: <code>{anime_id}</code>\n"
        f"📁 Tur: {data.get('type', 'anime')}\n"
        f"📅 Yil: {data.get('year', '—')}\n"
        f"🎭 Janr: {genres_str}\n"
        f"🏷 Teglar: {tags_str}\n"
        f"🎭 Mood: {mood_str}\n"
        f"⭐ Reyting: {data.get('rating', 0.0)}\n"
        f"🎞 Qismlar: {data.get('episodes', '—')}\n"
        f"📊 Status: {data.get('status', 'ongoing')}\n"
        f"🔗 Related: {related_str}\n"
        f"🔒 Pro-locked: {'Ha' if data.get('is_pro_locked') else 'Yo'q'}"
        f"{err_str}"
    )

    # Poster bor bo'lsa yuborish
    poster = data.get("poster_url") or data.get("poster_file_id")
    if poster and (poster.startswith("http") or len(poster) > 50):
        try:
            await msg.answer_photo(photo=poster, caption=success_text, parse_mode="HTML")
        except Exception:
            await msg.answer(success_text, parse_mode="HTML")
    else:
        await msg.answer(success_text, parse_mode="HTML")


@pro_admin_router.callback_query(F.data.startswith("json_update_"))
async def json_update_confirm(call: types.CallbackQuery):
    """JSON bilan mavjud kontentni yangilash."""
    if not await is_admin(call.from_user.id):
        return

    anime_id = int(call.data.replace("json_update_", ""))
    await call.message.edit_text(
        f"✏️ ID <code>{anime_id}</code> ni yangilash uchun yangi JSON yuboring.\n\n"
        f"⚠️ Barcha mavjud ma'lumotlar yangi JSON bilan almashtiriladi.",
        parse_mode="HTML"
    )
    await call.answer()


@pro_admin_router.callback_query(F.data == "json_cancel")
async def json_cancel(call: types.CallbackQuery):
    await call.message.edit_text("❌ Bekor qilindi.")
    await call.answer()


def _build_anime_from_json(data: dict) -> Anime:
    """JSON dict → Anime model obyekti."""
    return Anime(
        id=data["id"],
        title=data["title"],
        content_type=data.get("type", "anime"),
        year=data.get("year"),
        genres=data.get("genres", []),
        tags=data.get("tags",   []),
        mood=data.get("mood",   []),
        rating=float(data.get("rating", 0.0)),
        rating_count=0,
        episodes_count=data.get("episodes"),
        duration=data.get("duration"),
        status=data.get("status", "ongoing"),
        description=data.get("description", ""),
        popularity=float(data.get("popularity", 0.0)),
        is_pro_locked=bool(data.get("is_pro_locked", False)),
        # poster va trailer: URL yoki file_id
        inline_thumbnail_url=data.get("poster_url") or data.get("poster_file_id"),
        poster_file_id=data.get("poster_file_id") or data.get("poster_url"),
        trailer_file_id=data.get("trailer_url") or data.get("trailer_file_id"),
    )


# ═══════════════════════════════════════════════════════════
#  PRO LOCK TOGGLE
# ═══════════════════════════════════════════════════════════

@pro_admin_router.message(Command("pro_lock"))
async def toggle_pro_lock(msg: Message):
    """
    /pro_lock <anime_id>  — Pro lockni yoqish/o'chirish
    """
    if not await is_admin(msg.from_user.id):
        return

    parts = msg.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.answer(
            "❌ Format: <code>/pro_lock 1234</code>",
            parse_mode="HTML"
        )

    anime_id = int(parts[1])
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await msg.answer(f"❌ ID {anime_id} topilmadi!")

        anime.is_pro_locked = not anime.is_pro_locked
        await session.commit()

        status = "🔒 Pro-locked" if anime.is_pro_locked else "🔓 Ochiq"
        await msg.answer(
            f"✅ <b>{anime.title}</b>\n{status}",
            parse_mode="HTML"
        )


# ═══════════════════════════════════════════════════════════
#  PRO STATISTIKA
# ═══════════════════════════════════════════════════════════

@pro_admin_router.message(Command("pro_stats"))
async def pro_stats(msg: Message):
    """
    /pro_stats — kengaytirilgan statistika
    """
    if not await is_admin(msg.from_user.id):
        return

    from database.models import User, ViewRecord
    from datetime import datetime, timedelta

    async with AsyncSessionLocal() as session:
        total_users = await session.scalar(
            select(func.count(User.telegram_id))
        )
        pro_users = await session.scalar(
            select(func.count(User.telegram_id)).where(User.is_pro == True)
        )
        total_animes = await session.scalar(
            select(func.count(Anime.id))
        )

        # Turlarga ajratish
        type_counts = {}
        for t in ["anime", "movie", "serial", "dorama"]:
            cnt = await session.scalar(
                select(func.count(Anime.id)).where(Anime.content_type == t)
            )
            type_counts[t] = cnt or 0

        # 7 kunlik views
        week_ago = datetime.utcnow() - timedelta(days=7)
        week_views = await session.scalar(
            select(func.count(ViewRecord.id))
            .where(ViewRecord.viewed_at >= week_ago)
        )

        # Pro locked
        pro_locked = await session.scalar(
            select(func.count(Anime.id)).where(Anime.is_pro_locked == True)
        )

        # Top 3 trending
        top3_q = await session.execute(
            select(Anime.title, Anime.views)
            .order_by(Anime.views.desc())
            .limit(3)
        )
        top3 = top3_q.fetchall()

    top3_text = "\n".join(f"  {i+1}. {r[0]} ({r[1]} ko'rish)" for i, r in enumerate(top3))

    await msg.answer(
        f"📊 <b>Kaworai Pro Statistikasi</b>\n\n"
        f"👤 Jami foydalanuvchilar: <b>{total_users}</b>\n"
        f"⭐ Pro foydalanuvchilar: <b>{pro_users}</b>\n\n"
        f"🎬 Jami kontent: <b>{total_animes}</b>\n"
        f"  🎌 Anime: {type_counts['anime']}\n"
        f"  🎥 Kino: {type_counts['movie']}\n"
        f"  📺 Serial: {type_counts['serial']}\n"
        f"  🌸 Dorama: {type_counts['dorama']}\n"
        f"  🔒 Pro-locked: {pro_locked}\n\n"
        f"👁 7 kunlik ko'rishlar: <b>{week_views}</b>\n\n"
        f"🔥 Top 3 kontent:\n{top3_text}",
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════════════════
#  USER PRO BOSHQARISH
# ═══════════════════════════════════════════════════════════

@pro_admin_router.message(Command("set_pro"))
async def set_pro_user(msg: Message):
    """
    /set_pro <user_id> [days]
    Userni Pro qilish. Days ko'rsatilmasa — abadiy.
    """
    if not await is_admin(msg.from_user.id):
        return

    parts = msg.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.answer(
            "Format: <code>/set_pro 123456789</code>\n"
            "Yoki: <code>/set_pro 123456789 30</code> (30 kunlik)",
            parse_mode="HTML"
        )

    user_id = int(parts[1])
    days    = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else None

    from database.models import User
    from datetime import datetime, timedelta

    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            return await msg.answer(f"❌ User {user_id} topilmadi!")

        user.is_pro = True
        if days:
            user.pro_until = datetime.utcnow() + timedelta(days=days)
        else:
            user.pro_until = None   # Abadiy

        await session.commit()

        until_str = f"{days} kun" if days else "Abadiy"
        await msg.answer(
            f"✅ <b>{user.full_name}</b> Pro qilindi!\n"
            f"Muddat: {until_str}",
            parse_mode="HTML"
        )


@pro_admin_router.message(Command("remove_pro"))
async def remove_pro_user(msg: Message):
    """
    /remove_pro <user_id>
    """
    if not await is_admin(msg.from_user.id):
        return

    parts = msg.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await msg.answer("Format: <code>/remove_pro 123456789</code>", parse_mode="HTML")

    user_id = int(parts[1])
    from database.models import User

    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            return await msg.answer(f"❌ User {user_id} topilmadi!")

        user.is_pro    = False
        user.pro_until = None
        await session.commit()

        await msg.answer(
            f"✅ <b>{user.full_name}</b> Pro huquqi olib tashlandi.",
            parse_mode="HTML"
        )