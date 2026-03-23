from aiogram import Router, F, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from sqlalchemy import select, func

# Importlarni tekshiring
from states.admin_states import AddAnime
from database.models import Anime, Admin, User
from database.engine import AsyncSessionLocal  # Nomini to'g'irladik
import os

admin_router = Router()

# .env dan adminlarni olish (list ko'rinishida)
ADMINS = os.getenv("ADMIN_ID", "").split(",")

simple_admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Anime qo'shish")],
        [KeyboardButton(text="📊 Statistika")],
        [KeyboardButton(text="🔙 Chiqish")],
    ],
    resize_keyboard=True
)

@admin_router.message(Command("admin"))
async def admin_entry(msg: Message, state: FSMContext):
    # To'g'ri session chaqirish usuli
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admin).where(Admin.telegram_id == msg.from_user.id))
        admin = result.scalar_one_or_none()
        
        if not admin:
            # ADMINS ro'yxatida borligini tekshirish
            if str(msg.from_user.id) in ADMINS:
                new_admin = Admin(telegram_id=msg.from_user.id, role="owner", nickname=msg.from_user.full_name)
                session.add(new_admin)
                await session.commit()
                admin = new_admin
            else:
                await msg.answer("Siz admin emassiz. ❌")
                return

        role_text = "Owner" if admin.role == "owner" else "Partner"
        await msg.answer(f"🛠 {role_text} Admin Panel ochildi", reply_markup=simple_admin_kb)

@admin_router.message(F.text == "📊 Statistika")
async def stats(msg: Message):
    async with AsyncSessionLocal() as session:
        # Count so'rovlari
        user_count = await session.scalar(select(func.count(User.telegram_id)))
        anime_count = await session.scalar(select(func.count(Anime.id)))
        
        # Oxirgi qo'shilgan anime
        top_query = select(Anime).order_by(Anime.id.desc()).limit(1)
        res = await session.execute(top_query)
        last_anime = res.scalar_one_or_none()
        title = last_anime.title if last_anime else "Mavjud emas"

    await msg.answer(
        f"📊 <b>Statistika:</b>\n\n"
        f"👤 Foydalanuvchilar: <code>{user_count or 0}</code>\n"
        f"🎬 Jami animelar: <code>{anime_count or 0}</code>\n"
        f"🌟 Oxirgi qo'shilgan: {title}",
        parse_mode="HTML"
    )

@admin_router.message(F.text == "🔙 Chiqish")
async def exit_admin(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Admin paneldan chiqdingiz.", reply_markup=types.ReplyKeyboardRemove())