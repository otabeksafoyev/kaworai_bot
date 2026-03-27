import os
from aiogram import Router, F, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func

# Loyihangiz importlari
from states.admin_states import AddAnime, AddChannel
from database.models import Anime, Admin, User, SubscriptionChannel, Series
from database.engine import AsyncSessionLocal 

admin_router = Router()

# .env dan ma'lumotlar
ADMINS = os.getenv("ADMIN_ID", "").split(",")
SECRET_CHANNEL_ID = int(os.getenv("SECRET_CHANNEL_ID", "0"))  # Majburiy!

# ====================== ADMIN TEKSHIRISH ======================
async def is_admin(user_id: int) -> bool:
    """Foydalanuvchi adminmi yoki yo'qmi tekshiradi"""
    if str(user_id) in ADMINS:
        return True
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Admin).where(Admin.telegram_id == user_id)
        )
        return result.scalar_one_or_none() is not None


# ====================== TUGMALAR ======================
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


# ====================== ADMIN PANELGA KIRISH ======================
@admin_router.message(Command("admin"))
async def admin_entry(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return await msg.answer("❌ Siz admin emassiz!")

    async with AsyncSessionLocal() as session:
        admin = (await session.execute(
            select(Admin).where(Admin.telegram_id == msg.from_user.id)
        )).scalar_one_or_none()

        # Agar .env dagi ADMIN_ID bo'lsa, bazaga qo'shamiz
        if not admin and str(msg.from_user.id) in ADMINS:
            admin = Admin(
                telegram_id=msg.from_user.id,
                role="owner",
                nickname=msg.from_user.full_name
            )
            session.add(admin)
            await session.commit()

        await msg.answer(
            f"🛠 <b>Kaworai Admin Panel</b>\nRol: {admin.role.upper()}", 
            reply_markup=admin_main_kb, 
            parse_mode="HTML"
        )


# ====================== BEKOR QILISH ======================
@admin_router.message(F.text == "🚫 Bekor qilish")
async def cancel_action(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.clear()
    await msg.answer("Amal bekor qilindi.", reply_markup=admin_main_kb)


# ====================== ANIME QO'SHISH ======================
@admin_router.message(F.text == "➕ Anime qo'shish")
async def add_anime_start(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.set_state(AddAnime.waiting_id)
    await msg.answer("🆔 Yangi Anime uchun ID kiriting (faqat raqam):", reply_markup=cancel_kb)


@admin_router.message(AddAnime.waiting_id)
async def process_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if not msg.text.isdigit():
        return await msg.answer("ID faqat raqam bo'lishi kerak!")
    await state.update_data(anime_id=int(msg.text))
    await state.set_state(AddAnime.waiting_title)
    await msg.answer("📝 Anime nomini kiriting:")


@admin_router.message(AddAnime.waiting_title)
async def process_title(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.update_data(title=msg.text)
    await state.set_state(AddAnime.waiting_desc)
    await msg.answer("📖 Anime tavsifini kiriting:")


@admin_router.message(AddAnime.waiting_desc)
async def process_desc(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.update_data(desc=msg.text)
    await state.set_state(AddAnime.waiting_genres)
    await msg.answer("🎭 Janrlarni kiriting (vergul bilan, masalan: Jangari, Sarguzasht):")


@admin_router.message(AddAnime.waiting_genres)
async def process_genres(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    genres_list = [g.strip() for g in msg.text.split(",")]
    await state.update_data(genres=genres_list)
    await state.set_state(AddAnime.waiting_year)
    await msg.answer("📅 Chiqarilgan yilini kiriting:")


@admin_router.message(AddAnime.waiting_year)
async def process_year(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if not msg.text.isdigit():
        return await msg.answer("Yilni raqamda kiriting!")
    await state.update_data(year=int(msg.text))
    await state.set_state(AddAnime.waiting_poster)
    await msg.answer("🖼 Anime posterini (rasm) yuboring:")


@admin_router.message(AddAnime.waiting_poster, F.photo)
async def process_poster(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    data = await state.get_data()
    photo_id = msg.photo[-1].file_id
    
    async with AsyncSessionLocal() as session:
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
    await msg.answer(f"✅ <b>{data['title']}</b> bazaga qo'shildi!", 
                     reply_markup=admin_main_kb, parse_mode="HTML")


# ====================== QISM QO'SHISH (Admin tugmasi) ======================
@admin_router.message(F.text == "🎞 Qism qo'shish")
async def add_episode_start(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    
    await msg.answer(
        "✅ <b>Maxfiy kanal orqali qism yuklash yoqildi!</b>\n\n"
        "Endi videolarni quyidagi maxfiy kanalingizga yuklang:\n\n"
        f"<b>Kanal ID:</b> <code>{SECRET_CHANNEL_ID}</code>\n\n"
        "Har bir video uchun captionda quyidagi formatni ishlatish shart:\n\n"
        "<b>ID: 388\n"
        "Qism: 13</b>\n\n"
        "Qo‘shimcha matn yozish ham mumkin (masalan: episode nomi).",
        parse_mode="HTML"
    )


# ====================== MAXFIY KANALDAN AVTOMATIK QO‘SHISH ======================
@admin_router.channel_post(F.chat.id == SECRET_CHANNEL_ID)
async def add_episode_from_channel(message: Message):
    """Maxfiy kanaldan kelgan videoni avtomatik qo'shadi"""
    if not (message.video or message.document):
        return

    caption = (message.caption or message.text or "").strip()
    file_id = message.video.file_id if message.video else message.document.file_id

    anime_id = None
    episode = None

    # Captionni qatorlarga bo'lib, ID va Qism ni qidiramiz
    for line in caption.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        lower_line = line.lower()
        
        if lower_line.startswith("id:"):
            try:
                anime_id = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
                
        elif lower_line.startswith(("qism:", "episode:", "part:")):
            try:
                episode = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass

    if anime_id is None or episode is None:
        try:
            await message.answer(
                "❌ **Noto'g'ri format!**\n\n"
                "To'g'ri format quyidagicha bo'lishi kerak:\n"
                "<b>ID: 388\nQism: 13</b>",
                parse_mode="HTML"
            )
        except:
            pass
        return

    async with AsyncSessionLocal() as session:
        # Anime mavjudligini tekshirish
        anime = await session.get(Anime, anime_id)
        if not anime:
            await message.answer(f"❌ Anime ID {anime_id} bazada topilmadi!")
            return

        # Oxirgi qism raqamini olish
        result = await session.execute(
            select(func.max(Series.episode)).where(Series.anime_id == anime_id)
        )
        last_ep = result.scalar() or 0

        # Agar kiritilgan qism oldingisidan kichik yoki teng bo'lsa, avtomatik +1 qilamiz
        if episode <= last_ep:
            episode = last_ep + 1

        # Yangi seriyani saqlash
        new_series = Series(
            anime_id=anime_id,
            episode=episode,
            file_id=file_id
        )
        session.add(new_series)
        await session.commit()

    # Muvaffaqiyatli qo'shilgani haqida xabar
    success_text = (
        f"✅ <b>{anime.title}</b>\n"
        f"🎞 {episode}-qism muvaffaqiyatli qo'shildi!\n"
        f"📥 File ID: <code>{file_id}</code>"
    )
    try:
        await message.answer(success_text, parse_mode="HTML")
    except:
        pass


# ====================== QOLGAN ADMIN FUNKSIYALARI ======================
@admin_router.message(F.text == "📢 Kanal sozlamalari")
async def channel_manager(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    
    async with AsyncSessionLocal() as session:
        channels = (await session.execute(select(SubscriptionChannel))).scalars().all()
        
        text = "📢 <b>Majburiy obuna kanallari:</b>\n\n"
        kb = InlineKeyboardBuilder()
        
        for ch in channels:
            text += f"🔹 {ch.username} (ID: {ch.channel_id})\n"
            kb.row(InlineKeyboardButton(
                text=f"❌ {ch.username} o'chirish", 
                callback_data=f"del_ch_{ch.id}"
            ))
        
        kb.row(InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_channel"))
        
        await msg.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@admin_router.callback_query(F.data == "add_channel")
async def start_add_channel(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(AddChannel.waiting_id)
    await call.message.answer("Kanal ID sini kiriting (masalan: -100...):")
    await call.answer()


@admin_router.message(AddChannel.waiting_id)
async def save_ch_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.update_data(ch_id=msg.text)
    await state.set_state(AddChannel.waiting_username)
    await msg.answer("Kanal username kiriting (masalan: @kanal):")


@admin_router.message(AddChannel.waiting_username)
async def save_channel(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    data = await state.get_data()
    async with AsyncSessionLocal() as session:
        new_ch = SubscriptionChannel(channel_id=int(data['ch_id']), username=msg.text)
        session.add(new_ch)
        await session.commit()
    await state.clear()
    await msg.answer("✅ Kanal qo'shildi!", reply_markup=admin_main_kb)


@admin_router.message(F.text == "📊 Statistika")
async def show_stats(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    async with AsyncSessionLocal() as session:
        u_count = await session.scalar(select(func.count(User.telegram_id)))
        a_count = await session.scalar(select(func.count(Anime.id)))
        s_count = await session.scalar(select(func.count(Series.id)))
    
    await msg.answer(
        f"📊 <b>Bot Statistikasi:</b>\n\n"
        f"👤 Foydalanuvchilar: {u_count}\n"
        f"🎬 Animelar: {a_count}\n"
        f"🎞 Jami seriyalar: {s_count}", 
        parse_mode="HTML"
    )


@admin_router.message(F.text == "✉️ Xabar yuborish")
async def broadcast_start(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer("Xabarni yuboring (Rasm, Video yoki Matn):", reply_markup=cancel_kb)
    await state.set_state("waiting_broadcast")


@admin_router.message(F.state == "waiting_broadcast")
async def broadcast_send(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.clear()
    await msg.answer("🚀 Yuborish boshlandi...", reply_markup=admin_main_kb)
    
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User.telegram_id))).scalars().all()
        count = 0
        for user_id in users:
            try:
                await msg.copy_to(chat_id=user_id)
                count += 1
            except:
                pass
    await msg.answer(f"✅ {count} kishiga yuborildi.")


@admin_router.message(F.text == "🔙 Chiqish")
async def exit_admin(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.clear()
    await msg.answer("Panel yopildi.", reply_markup=ReplyKeyboardRemove())