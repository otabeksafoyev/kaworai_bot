import os
from aiogram import Router, F, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func, delete

# Proyektdagi importlar
from states.admin_states import AddAnime, AddChannel, AddPartner
from database.models import Anime, Admin, User, SubscriptionChannel, Series
from database.engine import AsyncSessionLocal 

admin_router = Router()

# .env dan ma'lumotlarni olish
ADMINS = os.getenv("ADMIN_ID", "").split(",")
NEWS_CHANNEL = os.getenv("NEWS_CHANNEL_ID")

# --- TUGMALAR ---
admin_main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Anime qo'shish"), KeyboardButton(text="🎞 Qism qo'shish")],
        [KeyboardButton(text="📢 Kanal sozlamalari"), KeyboardButton(text="📊 Statistika")],
        [KeyboardButton(text="✉️ Xabar yuborish"), KeyboardButton(text="🔙 Chiqish")],
    ],
    resize_keyboard=True
)

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🚫 Bekor qilish")]],
    resize_keyboard=True
)

# --- ADMIN PANELGA KIRISH ---
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
            await msg.answer(f"🛠 <b>Kaworai Admin Panel</b>\nRol: {admin.role.upper()}", 
                             reply_markup=admin_main_kb, parse_mode="HTML")
        else:
            await msg.answer("Siz admin emassiz. ❌")

@admin_router.message(F.text == "🚫 Bekor qilish")
async def cancel_action(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Amal bekor qilindi.", reply_markup=admin_main_kb)

# --- ANIME QO'SHISH BOSQICHLARI ---
@admin_router.message(F.text == "➕ Anime qo'shish")
async def add_anime_start(msg: Message, state: FSMContext):
    await state.set_state(AddAnime.waiting_id)
    await msg.answer("🆔 Yangi Anime uchun ID kiriting (faqat raqam):", reply_markup=cancel_kb)

@admin_router.message(AddAnime.waiting_id)
async def process_id(msg: Message, state: FSMContext):
    if not msg.text.isdigit():
        return await msg.answer("ID faqat raqam bo'lishi kerak!")
    await state.update_data(anime_id=int(msg.text))
    await state.set_state(AddAnime.waiting_title)
    await msg.answer("📝 Anime nomini kiriting:")

@admin_router.message(AddAnime.waiting_title)
async def process_title(msg: Message, state: FSMContext):
    await state.update_data(title=msg.text)
    await state.set_state(AddAnime.waiting_desc)
    await msg.answer("📖 Anime tavsifini kiriting:")

@admin_router.message(AddAnime.waiting_desc)
async def process_desc(msg: Message, state: FSMContext):
    await state.update_data(desc=msg.text)
    await state.set_state(AddAnime.waiting_genres)
    await msg.answer("🎭 Janrlarni kiriting (vergul bilan, masalan: Jangari, Sarguzasht):")

@admin_router.message(AddAnime.waiting_genres)
async def process_genres(msg: Message, state: FSMContext):
    genres_list = [g.strip() for g in msg.text.split(",")]
    await state.update_data(genres=genres_list)
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
            await msg.answer("❌ Bu ID allaqachon mavjud! Boshqa ID kiriting.")
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
    await msg.answer(f"✅ <b>{data['title']}</b> bazaga qo'shildi!", reply_markup=admin_main_kb, parse_mode="HTML")

# --- QISM (SERIYA) QO'SHISH ---
@admin_router.message(F.text == "🎞 Qism qo'shish")
async def add_episode_start(msg: Message, state: FSMContext):
    await state.set_state(AddAnime.waiting_series)
    await msg.answer("Qaysi Anime ID uchun qism qo'shamiz?", reply_markup=cancel_kb)

@admin_router.message(AddAnime.waiting_series)
async def process_series_id(msg: Message, state: FSMContext):
    if not msg.text.isdigit():
        return await msg.answer("ID raqam bo'lishi kerak!")
    
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, int(msg.text))
        if not anime:
            return await msg.answer("❌ Anime topilmadi!")
        
        await state.update_data(current_anime_id=anime.id)
        # Oxirgi qismni aniqlash
        result = await session.execute(select(func.max(Series.episode)).where(Series.anime_id == anime.id))
        last_ep = result.scalar() or 0
        
        await msg.answer(f"🎬 Anime: {anime.title}\nOxirgi qism: {last_ep}\n\n<b>Endi videoni yuboring:</b>", parse_mode="HTML")
        await state.set_state("waiting_video")

@admin_router.message(F.video | F.document, F.state == "waiting_video")
async def save_episode(msg: Message, state: FSMContext):
    data = await state.get_data()
    file_id = msg.video.file_id if msg.video else msg.document.file_id
    
    async with AsyncSessionLocal() as session:
        # Keyingi qism raqamini olish
        result = await session.execute(select(func.max(Series.episode)).where(Series.anime_id == data['current_anime_id']))
        next_ep = (result.scalar() or 0) + 1
        
        new_series = Series(
            anime_id=data['current_anime_id'],
            episode=next_ep,
            file_id=file_id
        )
        session.add(new_series)
        await session.commit()
        
        await msg.answer(f"✅ {next_ep}-qism qo'shildi!", reply_markup=admin_main_kb)
    await state.clear()

# --- MAJBURIY OBUNA SOZLAMALARI ---
@admin_router.message(F.text == "📢 Kanal sozlamalari")
async def channel_manager(msg: Message):
    async with AsyncSessionLocal() as session:
        channels = (await session.execute(select(SubscriptionChannel))).scalars().all()
        text = "📢 <b>Majburiy obuna kanallari:</b>\n\n"
        kb = InlineKeyboardBuilder()
        
        for ch in channels:
            text += f"🔹 {ch.username} (ID: {ch.channel_id})\n"
            kb.row(InlineKeyboardButton(text=f"❌ {ch.username} o'chirish", callback_data=f"del_ch_{ch.id}"))
        
        kb.row(InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_channel"))
        await msg.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@admin_router.callback_query(F.data == "add_channel")
async def start_add_channel(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddChannel.waiting_id)
    await call.message.answer("Kanal ID sini kiriting (masalan: -100...):")
    await call.answer()

@admin_router.message(AddChannel.waiting_id)
async def save_ch_id(msg: Message, state: FSMContext):
    await state.update_data(ch_id=msg.text)
    await state.set_state(AddChannel.waiting_username)
    await msg.answer("Kanal username kiriting (masalan: @kanal):")

@admin_router.message(AddChannel.waiting_username)
async def save_channel(msg: Message, state: FSMContext):
    data = await state.get_data()
    async with AsyncSessionLocal() as session:
        new_ch = SubscriptionChannel(channel_id=int(data['ch_id']), username=msg.text)
        session.add(new_ch)
        await session.commit()
    await state.clear()
    await msg.answer("✅ Kanal qo'shildi!", reply_markup=admin_main_kb)

# --- STATISTIKA ---
@admin_router.message(F.text == "📊 Statistika")
async def show_stats(msg: Message):
    async with AsyncSessionLocal() as session:
        u_count = await session.scalar(select(func.count(User.telegram_id)))
        a_count = await session.scalar(select(func.count(Anime.id)))
        s_count = await session.scalar(select(func.count(Series.id)))
    
    await msg.answer(f"📊 <b>Bot Statistikasi:</b>\n\n👤 Foydalanuvchilar: {u_count}\n🎬 Animelar: {a_count}\n🎞 Jami seriyalar: {s_count}", parse_mode="HTML")

# --- BROADCAST ---
@admin_router.message(F.text == "✉️ Xabar yuborish")
async def broadcast_start(msg: Message, state: FSMContext):
    await msg.answer("Xabarni yuboring (Rasm, Video yoki Matn):", reply_markup=cancel_kb)
    await state.set_state("waiting_broadcast")

@admin_router.message(F.state == "waiting_broadcast")
async def broadcast_send(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("🚀 Yuborish boshlandi...", reply_markup=admin_main_kb)
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User.telegram_id))).scalars().all()
        count = 0
        for user_id in users:
            try:
                await msg.copy_to(chat_id=user_id)
                count += 1
            except: pass
    await msg.answer(f"✅ {count} kishiga yuborildi.")

@admin_router.message(F.text == "🔙 Chiqish")
async def exit_admin(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Panel yopildi.", reply_markup=ReplyKeyboardRemove())