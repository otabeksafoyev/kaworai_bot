from aiogram import Router, F, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from sqlalchemy import select, func

# Proyektdagi importlar
from states.admin_states import AddAnime
from database.models import Anime, Admin, User
from database.engine import AsyncSessionLocal 
import os

admin_router = Router()
ADMINS = os.getenv("ADMIN_ID", "").split(",")

# Tugmalar
simple_admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Anime qo'shish")],
        [KeyboardButton(text="📊 Statistika")],
        [KeyboardButton(text="🔙 Chiqish")],
    ],
    resize_keyboard=True
)

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🚫 Bekor qilish")]],
    resize_keyboard=True
)

# --- ADMIN KIRISH ---
@admin_router.message(Command("admin"))
async def admin_entry(msg: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admin).where(Admin.telegram_id == msg.from_user.id))
        admin = result.scalar_one_or_none()
        
        if not admin and str(msg.from_user.id) in ADMINS:
            new_admin = Admin(telegram_id=msg.from_user.id, role="owner", nickname=msg.from_user.full_name)
            session.add(new_admin)
            await session.commit()
            admin = new_admin
        
        if admin:
            await msg.answer(f"🛠 Admin Panel: {admin.role.upper()}", reply_markup=simple_admin_kb)
        else:
            await msg.answer("Siz admin emassiz. ❌")

# --- BEKOR QILISH ---
@admin_router.message(F.text == "🚫 Bekor qilish")
async def cancel_handler(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Jarayon bekor qilindi.", reply_markup=simple_admin_kb)

# --- ANIME QO'SHISH (FULL FLOW) ---

@admin_router.message(F.text == "➕ Anime qo'shish")
async def add_anime_start(msg: Message, state: FSMContext):
    await state.set_state(AddAnime.waiting_id)
    await msg.answer("🆔 Anime ID (raqam) kiriting:", reply_markup=cancel_kb)

@admin_router.message(AddAnime.waiting_id)
async def process_id(msg: Message, state: FSMContext):
    if not msg.text.isdigit():
        return await msg.answer("ID faqat raqam bo'lsin!")
    await state.update_data(anime_id=int(msg.text))
    await state.set_state(AddAnime.waiting_title)
    await msg.answer("📝 Anime nomini kiriting:")

@admin_router.message(AddAnime.waiting_title)
async def process_title(msg: Message, state: FSMContext):
    await state.update_data(title=msg.text)
    await state.set_state(AddAnime.waiting_desc)
    await msg.answer("📖 Anime tavsifini (description) kiriting:")

@admin_router.message(AddAnime.waiting_desc)
async def process_desc(msg: Message, state: FSMContext):
    await state.update_data(desc=msg.text)
    await state.set_state(AddAnime.waiting_genres)
    await msg.answer("🎭 Janrlarni kiriting (masalan: Sarguzasht, Komediya):")

@admin_router.message(AddAnime.waiting_genres)
async def process_genres(msg: Message, state: FSMContext):
    await state.update_data(genres=msg.text.split(", "))
    await state.set_state(AddAnime.waiting_year)
    await msg.answer("📅 Chiqarilgan yilini kiriting:")

@admin_router.message(AddAnime.waiting_year)
async def process_year(msg: Message, state: FSMContext):
    if not msg.text.isdigit():
        return await msg.answer("Yilni raqamda kiriting!")
    await state.update_data(year=int(msg.text))
    await state.set_state(AddAnime.waiting_poster)
    await msg.answer("🖼 Anime posterini (rasm) yuboring:")

@admin_router.message(AddAnime.waiting_poster, F.photo)
async def process_poster(msg: Message, state: FSMContext):
    data = await state.get_data()
    photo_id = msg.photo[-1].file_id
    
    async with AsyncSessionLocal() as session:
        # ID bandligini tekshirish
        existing = await session.get(Anime, data['anime_id'])
        if existing:
            await msg.answer(f"❌ ID {data['anime_id']} band! Boshqa ID tanlang.")
            await state.set_state(AddAnime.waiting_id)
            return

        new_anime = Anime(
            id=data['anime_id'],
            title=data['title'],
            description=data['desc'],
            genres=data['genres'],
            year=data['year'],
            poster_file_id=photo_id
        )
        session.add(new_anime)
        await session.commit()
    
    await state.clear()
    await msg.answer(f"✅ <b>{data['title']}</b> bazaga qo'shildi!", parse_mode="HTML", reply_markup=simple_admin_kb)

# --- STATISTIKA ---
@admin_router.message(F.text == "📊 Statistika")
async def stats(msg: Message):
    async with AsyncSessionLocal() as session:
        u_count = await session.scalar(select(func.count(User.telegram_id)))
        a_count = await session.scalar(select(func.count(Anime.id)))
    await msg.answer(f"👤 Foydalanuvchilar: {u_count}\n🎬 Animelar: {a_count}")

@admin_router.message(F.text == "🔙 Chiqish")
async def exit_admin(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Chiqildi.", reply_markup=ReplyKeyboardRemove())