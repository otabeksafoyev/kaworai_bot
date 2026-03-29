import asyncio
import os

from aiogram import Router, F, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func

from states.admin_states import AddAnime, AddChannel, EditAnime, BroadcastState
from database.models import Anime, Admin, User, SubscriptionChannel, Series
from database.engine import AsyncSessionLocal
from database.queries import (
    get_all_channels, add_channel, remove_channel, toggle_channel, get_news_channels
)
from data import config

admin_router = Router()

ADMINS = os.getenv("ADMIN_ID", "").split(",")
SECRET_CHANNEL_ID = config.SECRET_CHANNEL_ID
NEWS_CHANNEL_ID = config.NEWS_CHANNEL_ID


# ====================== ADMIN TEKSHIRISH ======================

async def is_admin(user_id: int) -> bool:
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
        [KeyboardButton(text="🎌 Anime boshqaruv"), KeyboardButton(text="📢 Kanal sozlamalari")],
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="✉️ Xabar yuborish")],
        [KeyboardButton(text="🔙 Chiqish")],
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

        if not admin and str(msg.from_user.id) in ADMINS:
            admin = Admin(
                telegram_id=msg.from_user.id,
                role="owner",
                nickname=msg.from_user.full_name
            )
            session.add(admin)
            await session.commit()

    await msg.answer(
        f"🛠 <b>Kaworai Admin Panel</b>\nRol: {admin.role.upper() if admin else 'OWNER'}",
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


# ====================== ANIME BOSHQARUV SUBMENU ======================

@admin_router.message(F.text == "🎌 Anime boshqaruv")
async def anime_manage_menu(msg: Message):
    if not await is_admin(msg.from_user.id):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Anime tahrirlash", callback_data="manage_edit_anime")],
        [InlineKeyboardButton(text="🗑 Anime o'chirish", callback_data="manage_delete_anime")],
        [InlineKeyboardButton(text="🎞 Qism oraliq o'chirish", callback_data="manage_delete_episodes")],
        [InlineKeyboardButton(text="❌ Yopish", callback_data="manage_close")],
    ])

    await msg.answer(
        "🎌 <b>Anime boshqaruv</b>\n\nNimani qilmoqchisiz?",
        reply_markup=kb,
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data == "manage_close")
async def manage_close(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("✅ Yopildi.")
    await call.answer()


# ====================== ANIME TAHRIRLASH (button orqali) ======================

@admin_router.callback_query(F.data == "manage_edit_anime")
async def manage_edit_anime_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    await state.set_state(EditAnime.waiting_anime_id)
    await state.update_data(action="edit")
    await call.message.answer(
        "✏️ <b>Anime tahrirlash</b>\n\nAnime ID sini kiriting:",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )
    await call.answer()


# ====================== ANIME O'CHIRISH (button orqali) ======================

@admin_router.callback_query(F.data == "manage_delete_anime")
async def manage_delete_anime_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    await state.set_state(EditAnime.waiting_delete_anime_id)
    await call.message.answer(
        "🗑 <b>Anime o'chirish</b>\n\nAnime ID sini kiriting:",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(EditAnime.waiting_delete_anime_id)
async def delete_anime_get_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam kiriting!")

    anime_id = int(msg.text)
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await msg.answer(f"❌ ID {anime_id} li anime topilmadi!")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"confirm_delete_{anime_id}"),
            InlineKeyboardButton(text="❌ Yo'q", callback_data="cancel_delete")
        ]
    ])
    await state.clear()
    await msg.answer(
        f"⚠️ <b>{anime.title}</b> animesini o'chirishni tasdiqlaysizmi?\n\n"
        f"Bu animening barcha qismlari ham o'chadi!",
        reply_markup=kb,
        parse_mode="HTML"
    )


# ====================== QISM ORALIQ O'CHIRISH ======================

@admin_router.callback_query(F.data == "manage_delete_episodes")
async def manage_delete_episodes_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    await state.set_state(EditAnime.waiting_delete_ep_anime_id)
    await call.message.answer(
        "🎞 <b>Qism oraliq o'chirish</b>\n\nAnime ID sini kiriting:",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(EditAnime.waiting_delete_ep_anime_id)
async def delete_ep_get_anime_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam kiriting!")

    anime_id = int(msg.text)
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await msg.answer(f"❌ ID {anime_id} li anime topilmadi!")

        # Mavjud qismlarni ko'rsatish
        result = await session.execute(
            select(func.min(Series.episode), func.max(Series.episode), func.count(Series.id))
            .where(Series.anime_id == anime_id)
        )
        min_ep, max_ep, total = result.one()

    if not total or total == 0:
        return await msg.answer(f"❌ <b>{anime.title}</b> da hali qismlar yo'q!", parse_mode="HTML")

    await state.update_data(delete_ep_anime_id=anime_id, delete_ep_anime_title=anime.title)
    await state.set_state(EditAnime.waiting_delete_ep_from)
    await msg.answer(
        f"🎬 <b>{anime.title}</b>\n"
        f"📊 Mavjud qismlar: <b>{min_ep}</b> dan <b>{max_ep}</b> gacha (jami {total} ta)\n\n"
        f"🔢 Qaysi qismdan o'chirishni boshlash kerak?\n"
        f"<i>Masalan: 3</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )


@admin_router.message(EditAnime.waiting_delete_ep_from)
async def delete_ep_get_from(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    if not msg.text.isdigit() or int(msg.text) < 1:
        return await msg.answer("❌ Musbat raqam kiriting!")

    from_ep = int(msg.text)
    await state.update_data(delete_ep_from=from_ep)
    await state.set_state(EditAnime.waiting_delete_ep_to)
    await msg.answer(
        f"🔢 Qaysi qism gacha o'chirish kerak?\n"
        f"<i>Masalan: 6 (ya'ni {from_ep} dan 6 gacha o'chiriladi)</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )


@admin_router.message(EditAnime.waiting_delete_ep_to)
async def delete_ep_get_to(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    if not msg.text.isdigit() or int(msg.text) < 1:
        return await msg.answer("❌ Musbat raqam kiriting!")

    data = await state.get_data()
    from_ep = data['delete_ep_from']
    to_ep = int(msg.text)
    anime_id = data['delete_ep_anime_id']
    anime_title = data['delete_ep_anime_title']

    if to_ep < from_ep:
        return await msg.answer(
            f"❌ Oxirgi qism ({to_ep}) boshlang'ichdan ({from_ep}) kichik bo'lmasligi kerak!"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"✅ Ha, {from_ep}-{to_ep} qismlarni o'chir",
                callback_data=f"confirm_del_eps_{anime_id}_{from_ep}_{to_ep}"
            )
        ],
        [InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_delete")]
    ])

    await state.clear()
    await msg.answer(
        f"⚠️ <b>{anime_title}</b>\n\n"
        f"🗑 <b>{from_ep}</b> dan <b>{to_ep}</b> gacha bo'lgan qismlar o'chiriladi.\n"
        f"Jami: <b>{to_ep - from_ep + 1} ta qism</b>\n\n"
        f"Tasdiqlaysizmi?",
        reply_markup=kb,
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data.startswith("confirm_del_eps_"))
async def confirm_delete_episodes(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return

    # format: confirm_del_eps_{anime_id}_{from}_{to}
    parts = call.data.replace("confirm_del_eps_", "").split("_")
    anime_id = int(parts[0])
    from_ep = int(parts[1])
    to_ep = int(parts[2])

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Series).where(
                Series.anime_id == anime_id,
                Series.episode >= from_ep,
                Series.episode <= to_ep
            )
        )
        episodes = result.scalars().all()
        count = len(episodes)

        for ep in episodes:
            await session.delete(ep)
        await session.commit()

    await call.message.edit_text(
        f"✅ <b>{from_ep}</b> dan <b>{to_ep}</b> gacha bo'lgan "
        f"<b>{count} ta qism</b> o'chirildi!",
        parse_mode="HTML"
    )
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


# ====================== ANIME QO'SHISH ======================

@admin_router.message(F.text == "➕ Anime qo'shish")
async def add_anime_start(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.set_state(AddAnime.waiting_id)
    await msg.answer(
        "🆔 Yangi Anime uchun ID kiriting (faqat raqam):\n"
        "<i>Masalan: 1, 2, 100 va h.k.</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )


@admin_router.message(AddAnime.waiting_id)
async def process_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    if not msg.text.isdigit():
        return await msg.answer("❌ ID faqat raqam bo'lishi kerak!")

    anime_id = int(msg.text)

    async with AsyncSessionLocal() as session:
        existing = await session.get(Anime, anime_id)
        if existing:
            async with AsyncSessionLocal() as session2:
                result = await session2.execute(select(func.max(Anime.id)))
                max_id = result.scalar() or 0
                suggested_id = max_id + 1
            return await msg.answer(
                f"❌ <b>ID {anime_id} allaqachon mavjud!</b>\n\n"
                f"💡 Bo'sh ID: <code>{suggested_id}</code>\n\n"
                f"Boshqa ID kiriting:",
                parse_mode="HTML"
            )

    await state.update_data(anime_id=anime_id)
    await state.set_state(AddAnime.waiting_title)
    await msg.answer("📝 Anime nomini kiriting:")


@admin_router.message(AddAnime.waiting_title)
async def process_title(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    await state.update_data(title=msg.text.strip())
    await state.set_state(AddAnime.waiting_desc)
    await msg.answer("📖 Anime tavsifini kiriting:")


@admin_router.message(AddAnime.waiting_desc)
async def process_desc(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    await state.update_data(desc=msg.text.strip())
    await state.set_state(AddAnime.waiting_genres)
    await msg.answer("🎭 Janrlarni kiriting (vergul bilan):\n<i>Masalan: Jangari, Sarguzasht</i>", parse_mode="HTML")


@admin_router.message(AddAnime.waiting_genres)
async def process_genres(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    genres_list = [g.strip() for g in msg.text.split(",")]
    await state.update_data(genres=genres_list)
    await state.set_state(AddAnime.waiting_year)
    await msg.answer("📅 Chiqarilgan yilini kiriting:")


@admin_router.message(AddAnime.waiting_year)
async def process_year(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Yilni raqamda kiriting!")
    await state.update_data(year=int(msg.text))
    await state.set_state(AddAnime.waiting_rating)
    await msg.answer(
        "⭐ Boshlang'ich reytingni kiriting:\n"
        "<i>Masalan: 8.5 yoki 0</i>",
        parse_mode="HTML"
    )


@admin_router.message(AddAnime.waiting_rating)
async def process_rating(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    try:
        rating = float(msg.text.replace(",", "."))
        if not (0 <= rating <= 10):
            return await msg.answer("❌ Reyting 0 dan 10 gacha bo'lishi kerak!")
    except ValueError:
        return await msg.answer("❌ Raqam kiriting! Masalan: 8.5 yoki 0")

    await state.update_data(rating=rating)
    await state.set_state(AddAnime.waiting_total_episodes)
    await msg.answer(
        "🎞 Anime nechta qismdan iborat?\n"
        "<i>Masalan: 12, 24, 50</i>",
        parse_mode="HTML"
    )


@admin_router.message(AddAnime.waiting_total_episodes)
async def process_total_episodes(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    if not msg.text.isdigit() or int(msg.text) < 1:
        return await msg.answer("❌ Musbat raqam kiriting! Masalan: 12")
    await state.update_data(total_episodes=int(msg.text))
    await state.set_state(AddAnime.waiting_poster)
    await msg.answer("🖼 Anime posterini (rasm) yuboring:")


@admin_router.message(AddAnime.waiting_poster, F.photo)
async def process_poster(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.update_data(poster_file_id=msg.photo[-1].file_id)
    await state.set_state(AddAnime.waiting_inline_url)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ URL siz davom etish", callback_data="skip_inline_url")]
    ])
    await msg.answer(
        "🖼 Inline qidiruv uchun <b>rasm URL</b> kiriting:\n\n"
        "<i>Masalan: https://i.imgur.com/abc.jpg</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data == "skip_inline_url")
async def skip_inline_url(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.update_data(inline_thumbnail_url=None)
    await state.set_state(AddAnime.waiting_trailer)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Traylersiz davom etish", callback_data="skip_trailer")]
    ])
    await call.message.answer(
        "🎬 Anime traylerini yuboring (video):\n\n"
        "Yoki traylersiz davom etish uchun tugmani bosing:",
        reply_markup=kb
    )
    await call.answer()


@admin_router.message(AddAnime.waiting_inline_url)
async def process_inline_url(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    url = msg.text.strip()
    if not url.startswith("http"):
        return await msg.answer("❌ URL https:// bilan boshlanishi kerak!", reply_markup=cancel_kb)
    await state.update_data(inline_thumbnail_url=url)
    await state.set_state(AddAnime.waiting_trailer)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Traylersiz davom etish", callback_data="skip_trailer")]
    ])
    await msg.answer(
        "🎬 Anime traylerini yuboring (video):\n\n"
        "Yoki traylersiz davom etish uchun tugmani bosing:",
        reply_markup=kb
    )


@admin_router.callback_query(F.data == "skip_trailer")
async def skip_trailer(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.update_data(trailer_file_id=None)
    await call.message.answer("⏳ Saqlanmoqda...")
    await _save_anime(call.message, state)
    await call.answer()


@admin_router.message(AddAnime.waiting_trailer, F.video)
async def process_trailer(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.update_data(trailer_file_id=msg.video.file_id)
    await _save_anime(msg, state)


async def _save_anime(msg: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    async with AsyncSessionLocal() as session:
        existing = await session.get(Anime, data['anime_id'])
        if existing:
            return await msg.answer("❌ Bu ID allaqachon mavjud!", reply_markup=admin_main_kb)

        new_anime = Anime(
            id=data['anime_id'],
            title=data['title'],
            description=data['desc'],
            genres=data['genres'],
            year=data['year'],
            rating=data.get('rating', 0.0),
            total_episodes=data.get('total_episodes', 0),
            poster_file_id=data['poster_file_id'],
            trailer_file_id=data.get('trailer_file_id'),
            inline_thumbnail_url=data.get('inline_thumbnail_url'),
        )
        session.add(new_anime)
        await session.commit()

    await msg.answer(
        f"✅ <b>{data['title']}</b> bazaga qo'shildi!\n\n"
        f"🎞 Qismlar soni: <b>{data.get('total_episodes', 0)} ta</b>\n\n"
        f"📢 Kanallarga yuborish: <b>Xabar yuborish → Anime post</b>",
        reply_markup=admin_main_kb,
        parse_mode="HTML"
    )
    await _send_admin_preview(msg, data)


async def _send_admin_preview(msg: Message, data: dict):
    genres_text = ", ".join(data.get('genres', [])) or "Nomalum"
    trailer_status = "✅ Bor" if data.get('trailer_file_id') else "❌ Yo'q"
    inline_status = "✅ Bor" if data.get('inline_thumbnail_url') else "❌ Yo'q"

    info_text = (
        f"📋 <b>Yangi anime qo'shildi!</b>\n\n"
        f"🎌 Nomi: <b>{data['title']}</b>\n"
        f"📅 Yil: {data['year']}\n"
        f"🎭 Janr: {genres_text}\n"
        f"⭐ Reyting: {data.get('rating', 0.0)}\n"
        f"🎞 Qismlar soni: {data.get('total_episodes', 0)} ta\n"
        f"🎬 Treyler: {trailer_status}\n"
        f"🖼 Inline URL: {inline_status}\n"
        f"🆔 ID: <code>{data['anime_id']}</code>\n\n"
        f"📖 {data['desc']}"
    )

    try:
        await msg.bot.send_photo(
            chat_id=config.ADMIN_ID,
            photo=data['poster_file_id'],
            caption=info_text,
            parse_mode="HTML"
        )
    except Exception as e:
        await msg.answer(f"⚠️ Preview xato: {e}")

    if data.get('trailer_file_id'):
        try:
            await msg.bot.send_video(
                chat_id=config.ADMIN_ID,
                video=data['trailer_file_id'],
                caption=f"🎬 <b>{data['title']}</b> — Treyler",
                parse_mode="HTML"
            )
        except Exception as e:
            await msg.answer(f"⚠️ Treyler preview xato: {e}")


# ====================== ANIME O'CHIRISH (command) ======================

@admin_router.message(Command("delete_anime"))
async def delete_anime_start(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.set_state(EditAnime.waiting_delete_anime_id)
    await msg.answer(
        "🗑 <b>Anime o'chirish</b>\n\nAnime ID sini kiriting:",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )


# ====================== QISM O'CHIRISH (command) ======================

@admin_router.message(Command("delete_episode"))
async def delete_episode_start(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer(
        "🗑 <b>Qism o'chirish</b>\n\n"
        "Format: <code>anime_id qism_raqami</code>\n"
        "Masalan: <code>388 5</code>",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )
    await state.set_state(EditAnime.waiting_anime_id)
    await state.update_data(action="delete_episode")


# ====================== ANIME EDIT (command) ======================

@admin_router.message(Command("edit_anime"))
async def edit_anime_start(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.set_state(EditAnime.waiting_anime_id)
    await state.update_data(action="edit")
    await msg.answer(
        "✏️ <b>Anime tahrirlash</b>\n\nAnime ID sini kiriting:",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )


@admin_router.message(EditAnime.waiting_anime_id)
async def edit_get_anime(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    data = await state.get_data()
    action = data.get("action", "edit")

    if action == "delete_episode":
        parts = msg.text.strip().split()
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            return await msg.answer(
                "❌ Format: <code>anime_id qism_raqami</code>\nMasalan: <code>388 5</code>",
                parse_mode="HTML"
            )
        anime_id, ep_num = int(parts[0]), int(parts[1])
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Series).where(Series.anime_id == anime_id, Series.episode == ep_num)
            )
            ep = result.scalar_one_or_none()
            if not ep:
                return await msg.answer(f"❌ Anime {anime_id} da {ep_num}-qism topilmadi!")
            await session.delete(ep)
            await session.commit()
        await state.clear()
        return await msg.answer(f"✅ {anime_id}-anime {ep_num}-qism o'chirildi!", reply_markup=admin_main_kb)

    try:
        anime_id = int(msg.text.strip())
    except ValueError:
        return await msg.answer("❌ Raqam kiriting!")

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await msg.answer(f"❌ ID {anime_id} li anime topilmadi!")
        total = anime.total_episodes or 0
        title = anime.title

    await state.update_data(edit_anime_id=anime_id, edit_total_episodes=total)
    await state.set_state(EditAnime.waiting_field)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Nomi", callback_data="edit_title"),
         InlineKeyboardButton(text="📖 Tavsif", callback_data="edit_desc")],
        [InlineKeyboardButton(text="🎭 Janr", callback_data="edit_genres"),
         InlineKeyboardButton(text="📅 Yil", callback_data="edit_year")],
        [InlineKeyboardButton(text="🖼 Poster", callback_data="edit_poster"),
         InlineKeyboardButton(text="🎬 Treyler", callback_data="edit_trailer")],
        [InlineKeyboardButton(text="🖼 Inline URL", callback_data="edit_inline_url"),
         InlineKeyboardButton(text="⭐ Reyting", callback_data="edit_rating")],
        [InlineKeyboardButton(text="🔢 Qismlar soni", callback_data="edit_total_episodes"),
         InlineKeyboardButton(text="🎞 Qism videosi", callback_data="edit_episode")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="edit_cancel")],
    ])

    await msg.answer(
        f"✏️ <b>{title}</b>\n\nNimani tahrirlash kerak?",
        reply_markup=kb,
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete_anime(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    anime_id = int(call.data.replace("confirm_delete_", ""))
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if anime:
            title = anime.title
            await session.delete(anime)
            await session.commit()
            await call.message.edit_text(f"✅ <b>{title}</b> o'chirildi!", parse_mode="HTML")
        else:
            await call.message.edit_text("❌ Anime topilmadi!")
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "cancel_delete")
async def cancel_delete(call: types.CallbackQuery):
    await call.message.edit_text("❌ Bekor qilindi.")
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data.startswith("edit_"))
async def edit_field_selected(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return

    field = call.data.replace("edit_", "")

    if field == "cancel":
        await state.clear()
        await call.message.edit_text("❌ Bekor qilindi.")
        await call.message.answer("Panel:", reply_markup=admin_main_kb)
        await call.answer()
        return

    # Qism videosini o'zgartirish
    if field == "episode":
        data = await state.get_data()
        total = data.get('edit_total_episodes', 0)

        if not total or total == 0:
            await call.answer("❌ Bu animeda qismlar soni kiritilmagan!", show_alert=True)
            return

        kb = InlineKeyboardBuilder()
        for ep in range(1, total + 1):
            kb.button(text=f"🎞 {ep}-qism", callback_data=f"editep_{ep}")
        kb.adjust(4)
        kb.row(InlineKeyboardButton(text="❌ Bekor", callback_data="editep_cancel"))

        await state.set_state(EditAnime.waiting_episode_select)
        await call.message.answer(
            f"🎞 Qaysi qismni o'zgartirmoqchisiz?\n"
            f"<i>Jami: {total} ta qism</i>",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
        await call.answer()
        return

    field_names = {
        "title": "yangi nomini",
        "desc": "yangi tavsifini",
        "genres": "yangi janrlarini (vergul bilan)",
        "year": "yangi yilini (raqam)",
        "poster": "yangi posterini (rasm yuboring)",
        "trailer": "yangi traylerini (video yuboring)",
        "inline_url": "yangi inline URL sini",
        "rating": "yangi reytingini (masalan: 8.5)",
        "total_episodes": "yangi qismlar sonini (raqam)",
    }

    await state.update_data(edit_field=field)
    await state.set_state(EditAnime.waiting_value)
    await call.message.answer(
        f"✏️ Anime {field_names.get(field, field)}ni yuboring:",
        reply_markup=cancel_kb
    )
    await call.answer()


# ====================== QISM TANLASH ======================

@admin_router.callback_query(F.data.startswith("editep_"))
async def episode_selected(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return

    if call.data == "editep_cancel":
        await state.clear()
        await call.message.edit_text("❌ Bekor qilindi.")
        await call.message.answer("Panel:", reply_markup=admin_main_kb)
        await call.answer()
        return

    ep_num = int(call.data.replace("editep_", ""))
    await state.update_data(edit_episode_num=ep_num)
    await state.set_state(EditAnime.waiting_episode_video)
    await call.message.answer(
        f"🎬 {ep_num}-qism uchun yangi videoni yuboring:",
        reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(EditAnime.waiting_episode_video, F.video)
async def save_episode_video(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return

    data = await state.get_data()
    anime_id = data['edit_anime_id']
    ep_num = data['edit_episode_num']

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Series).where(Series.anime_id == anime_id, Series.episode == ep_num)
        )
        ep = result.scalar_one_or_none()

        if not ep:
            await state.clear()
            return await msg.answer(
                f"❌ {ep_num}-qism topilmadi! Avval maxfiy kanal orqali qism qo'shing.",
                reply_markup=admin_main_kb
            )

        ep.file_id = msg.video.file_id
        await session.commit()

    await state.clear()
    await msg.answer(f"✅ {ep_num}-qism videosi yangilandi!", reply_markup=admin_main_kb)


# ====================== EDIT VALUE SAQLASH ======================

@admin_router.message(EditAnime.waiting_value)
async def save_edit_value(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    data = await state.get_data()
    anime_id = data['edit_anime_id']
    field = data['edit_field']

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            await state.clear()
            return await msg.answer("❌ Anime topilmadi!", reply_markup=admin_main_kb)

        if field == "title":
            anime.title = msg.text.strip()
        elif field == "desc":
            anime.description = msg.text.strip()
        elif field == "genres":
            anime.genres = [g.strip() for g in msg.text.split(",")]
        elif field == "year":
            if not msg.text.isdigit():
                return await msg.answer("❌ Yilni raqamda kiriting!")
            anime.year = int(msg.text)
        elif field == "poster":
            if not msg.photo:
                return await msg.answer("❌ Rasm yuboring!")
            anime.poster_file_id = msg.photo[-1].file_id
        elif field == "trailer":
            if not msg.video:
                return await msg.answer("❌ Video yuboring!")
            anime.trailer_file_id = msg.video.file_id
        elif field == "inline_url":
            url = msg.text.strip()
            if not url.startswith("http"):
                return await msg.answer("❌ URL https:// bilan boshlanishi kerak!")
            anime.inline_thumbnail_url = url
        elif field == "rating":
            try:
                rating = float(msg.text.replace(",", "."))
                if not (0 <= rating <= 10):
                    return await msg.answer("❌ 0 dan 10 gacha bo'lishi kerak!")
                anime.rating = rating
            except ValueError:
                return await msg.answer("❌ Raqam kiriting!")
        elif field == "total_episodes":
            if not msg.text.isdigit() or int(msg.text) < 1:
                return await msg.answer("❌ Musbat raqam kiriting!")
            anime.total_episodes = int(msg.text)

        await session.commit()
        title = anime.title

    await state.clear()
    await msg.answer(f"✅ <b>{title}</b> yangilandi!", reply_markup=admin_main_kb, parse_mode="HTML")


# ====================== QISM QO'SHISH ======================

@admin_router.message(F.text == "🎞 Qism qo'shish")
async def add_episode_start(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer(
        "✅ <b>Maxfiy kanal orqali qism yuklash!</b>\n\n"
        f"Kanal ID: <code>{SECRET_CHANNEL_ID}</code>\n\n"
        "Caption formati:\n"
        "<b>ID: 388\nQism: 13</b>",
        parse_mode="HTML"
    )


@admin_router.channel_post(F.chat.id == SECRET_CHANNEL_ID)
async def add_episode_from_channel(message: Message):
    if not (message.video or message.document):
        return

    caption = (message.caption or message.text or "").strip()
    file_id = message.video.file_id if message.video else message.document.file_id

    anime_id = None
    episode = None

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
                "❌ Noto'g'ri format!\n\nTo'g'ri format:\n<b>ID: 388\nQism: 13</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            try:
                await message.answer(f"❌ Anime ID {anime_id} topilmadi!")
            except Exception:
                pass
            return

        result = await session.execute(
            select(func.max(Series.episode)).where(Series.anime_id == anime_id)
        )
        last_ep = result.scalar() or 0
        if episode <= last_ep:
            episode = last_ep + 1

        new_series = Series(anime_id=anime_id, episode=episode, file_id=file_id)
        session.add(new_series)
        await session.commit()

    try:
        await message.answer(
            f"✅ <b>{anime.title}</b> — {episode}-qism saqlandi!",
            parse_mode="HTML"
        )
    except Exception:
        pass

    try:
        await message.bot.send_message(
            chat_id=config.ADMIN_ID,
            text=(
                f"📥 <b>Yangi qism qo'shildi!</b>\n\n"
                f"🎬 Anime: <b>{anime.title}</b>\n"
                f"🎞 Qism: <b>{episode}-qism</b>\n"
                f"🆔 Anime ID: <code>{anime_id}</code>"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass


# ====================== KANAL SOZLAMALARI ======================

@admin_router.message(F.text == "📢 Kanal sozlamalari")
async def channel_manager(msg: Message):
    if not await is_admin(msg.from_user.id):
        return

    async with AsyncSessionLocal() as session:
        channels = await get_all_channels(session)

    if not channels:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Obuna kanali", callback_data="add_channel"),
             InlineKeyboardButton(text="📰 News kanal", callback_data="add_news_channel")]
        ])
        return await msg.answer("📢 <b>Hozircha kanallar yo'q.</b>", reply_markup=kb, parse_mode="HTML")

    text = "📢 <b>Kanallar ro'yxati:</b>\n\n"
    kb = InlineKeyboardBuilder()

    for ch in channels:
        status = "✅" if ch.is_active else "⛔"
        ch_type = "📰 News" if ch.is_news else ("🔒 Majburiy" if ch.require_check else "👁 Ko'rsatish")
        text += f"{status} {ch_type} — <b>{ch.channel_name}</b>\n🔗 {ch.channel_url}\n\n"
        btn_text = "⛔ Ochir" if ch.is_active else "✅ Yoq"
        kb.row(
            InlineKeyboardButton(text=f"{btn_text} | {ch.channel_name}", callback_data=f"toggle_ch_{ch.id}"),
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del_ch_{ch.id}")
        )

    kb.row(
        InlineKeyboardButton(text="➕ Obuna kanali", callback_data="add_channel"),
        InlineKeyboardButton(text="📰 News kanal", callback_data="add_news_channel")
    )

    await msg.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("toggle_ch_"))
async def toggle_channel_cb(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    ch_id = int(call.data.replace("toggle_ch_", ""))
    async with AsyncSessionLocal() as session:
        result = await toggle_channel(session, ch_id)
    if result is None:
        await call.answer("❌ Kanal topilmadi!", show_alert=True)
    else:
        status = "✅ Yoqildi" if result else "⛔ O'chirildi"
        await call.answer(f"Kanal {status}", show_alert=True)
    await channel_manager(call.message)


@admin_router.callback_query(F.data.startswith("del_ch_"))
async def delete_channel_cb(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    ch_id = int(call.data.replace("del_ch_", ""))
    async with AsyncSessionLocal() as session:
        success = await remove_channel(session, ch_id)
    if success:
        await call.answer("✅ Kanal o'chirildi!", show_alert=True)
        await channel_manager(call.message)
    else:
        await call.answer("❌ Kanal topilmadi!", show_alert=True)


@admin_router.callback_query(F.data == "add_channel")
async def start_add_channel(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    await state.set_state(AddChannel.waiting_name)
    await state.update_data(is_news_channel=False)
    await call.message.answer(
        "1️⃣ Tugmada chiqadigan <b>nom</b> kiriting:\n<i>Masalan: Anime Dunyosi</i>",
        parse_mode="HTML", reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.callback_query(F.data == "add_news_channel")
async def add_news_channel_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    await state.set_state(AddChannel.waiting_name)
    await state.update_data(is_news_channel=True)
    await call.message.answer(
        "📰 <b>News kanal qo'shish</b>\n\n1️⃣ Kanal nomini kiriting:",
        parse_mode="HTML", reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(AddChannel.waiting_name)
async def save_ch_name(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    await state.update_data(channel_name=msg.text.strip())
    await state.set_state(AddChannel.waiting_url)
    await msg.answer(
        "2️⃣ <b>Havola (URL)</b> kiriting:\n\nTelegram: <code>https://t.me/kanal_nomi</code>",
        parse_mode="HTML", reply_markup=cancel_kb
    )


@admin_router.message(AddChannel.waiting_url)
async def save_ch_url(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    url = msg.text.strip()
    if not url.startswith("http"):
        return await msg.answer("❌ URL https:// bilan boshlanishi kerak!", reply_markup=cancel_kb)

    data = await state.get_data()
    is_news = data.get('is_news_channel', False)
    await state.update_data(channel_url=url)

    if is_news:
        await state.set_state(AddChannel.waiting_channel_id)
        await msg.answer(
            "3️⃣ Telegram kanal ID sini kiriting:\n\n<i>Masalan: -1001234567890</i>",
            parse_mode="HTML", reply_markup=cancel_kb
        )
        return

    await state.set_state(AddChannel.waiting_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 Faqat ko'rsatish", callback_data="ch_type_show")],
        [InlineKeyboardButton(text="🔒 Majburiy obuna", callback_data="ch_type_required")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="ch_type_cancel")],
    ])
    await msg.answer(
        "3️⃣ Kanal turi:\n\n"
        "👁 <b>Faqat ko'rsatish</b> — obuna tekshirilmaydi\n"
        "🔒 <b>Majburiy obuna</b> — foydalanuvchi obuna bo'lishi shart",
        parse_mode="HTML", reply_markup=kb
    )


@admin_router.callback_query(F.data == "ch_type_cancel")
async def ch_type_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Bekor qilindi.")
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "ch_type_show")
async def ch_type_show(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    data = await state.get_data()
    await state.clear()
    async with AsyncSessionLocal() as session:
        ch = await add_channel(
            session=session, channel_name=data["channel_name"],
            channel_url=data["channel_url"], require_check=False, is_news=False,
        )
    await call.message.edit_text(
        f"✅ <b>Kanal qo'shildi!</b>\n\n📢 Nom: <b>{ch.channel_name}</b>\n"
        f"🔗 URL: {ch.channel_url}\n👁 Turi: Faqat ko'rsatish",
        parse_mode="HTML"
    )
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "ch_type_required")
async def ch_type_required(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    await state.set_state(AddChannel.waiting_channel_id)
    await call.message.edit_text(
        "4️⃣ Telegram kanal ID sini kiriting:\n\n<i>Masalan: -1001234567890</i>",
        parse_mode="HTML"
    )
    await call.answer()


@admin_router.message(AddChannel.waiting_channel_id)
async def save_ch_channel_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    try:
        channel_id = int(msg.text.strip())
    except ValueError:
        return await msg.answer(
            "❌ Noto'g'ri format!\nMasalan: <code>-1001234567890</code>",
            parse_mode="HTML", reply_markup=cancel_kb
        )
    data = await state.get_data()
    is_news = data.get('is_news_channel', False)
    await state.clear()
    async with AsyncSessionLocal() as session:
        ch = await add_channel(
            session=session, channel_name=data["channel_name"],
            channel_url=data["channel_url"], require_check=not is_news,
            is_news=is_news, channel_id=channel_id,
        )
    ch_type = "📰 News kanal" if is_news else "🔒 Majburiy obuna"
    await msg.answer(
        f"✅ <b>Kanal qo'shildi!</b>\n\n📢 Nom: <b>{ch.channel_name}</b>\n"
        f"🔗 URL: {ch.channel_url}\n🆔 Kanal ID: <code>{ch.channel_id}</code>\n📌 Turi: {ch_type}",
        reply_markup=admin_main_kb, parse_mode="HTML"
    )


# ====================== STATISTIKA ======================

@admin_router.message(F.text == "📊 Statistika")
async def show_stats(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    async with AsyncSessionLocal() as session:
        u_count = await session.scalar(select(func.count(User.telegram_id)))
        a_count = await session.scalar(select(func.count(Anime.id)))
        s_count = await session.scalar(select(func.count(Series.id)))
        ch_count = await session.scalar(select(func.count(SubscriptionChannel.id)))

    await msg.answer(
        f"📊 <b>Bot Statistikasi:</b>\n\n"
        f"👤 Foydalanuvchilar: <b>{u_count}</b>\n"
        f"🎬 Animelar: <b>{a_count}</b>\n"
        f"🎞 Jami seriyalar: <b>{s_count}</b>\n"
        f"📢 Kanallar: <b>{ch_count}</b>",
        parse_mode="HTML"
    )


# ====================== BROADCAST ======================

@admin_router.message(F.text == "✉️ Xabar yuborish")
async def broadcast_start(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Anime post (kanalga)", callback_data="broadcast_anime")],
        [InlineKeyboardButton(text="👥 Foydalanuvchilarga xabar", callback_data="broadcast_users")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="broadcast_cancel")],
    ])
    await msg.answer("📢 <b>Xabar yuborish</b>\n\nNimani yubormoqchisiz?", reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Bekor qilindi.")
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "broadcast_users")
async def broadcast_users_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_content)
    await call.message.answer(
        "📨 Foydalanuvchilarga yuboriladigan xabarni yuboring:\n"
        "<i>Matn, rasm, video yoki fayl bo'lishi mumkin</i>",
        parse_mode="HTML", reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.callback_query(F.data == "broadcast_anime")
async def broadcast_anime_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_anime_id)
    await call.message.answer("🎬 Anime ID sini kiriting:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.message(BroadcastState.waiting_anime_id)
async def broadcast_get_anime_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam kiriting!")

    anime_id = int(msg.text)
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await msg.answer(f"❌ ID {anime_id} li anime topilmadi!")
        await state.update_data(
            broadcast_anime_id=anime_id,
            broadcast_anime_title=anime.title,
            broadcast_anime_poster=anime.poster_file_id,
        )

    await state.set_state(BroadcastState.waiting_media_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Matn bilan", callback_data="bcast_text")],
        [InlineKeyboardButton(text="🖼 Poster bilan", callback_data="bcast_poster")],
        [InlineKeyboardButton(text="❌ Bekor", callback_data="broadcast_cancel")],
    ])
    await msg.answer(f"✅ <b>{anime.title}</b> tanlandi.\n\nPost turi:", reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.in_({"bcast_text", "bcast_poster"}))
async def broadcast_media_type(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.update_data(broadcast_type=call.data)
    await state.set_state(BroadcastState.waiting_anime_post_caption)
    await call.message.answer("✏️ Post uchun caption kiriting:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.message(BroadcastState.waiting_anime_post_caption)
async def broadcast_anime_caption(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    await state.update_data(broadcast_caption=msg.text.strip())
    data = await state.get_data()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yuborish", callback_data="bcast_confirm")],
        [InlineKeyboardButton(text="❌ Bekor", callback_data="broadcast_cancel")],
    ])
    preview_text = (
        f"📋 <b>Preview:</b>\n\n"
        f"🎬 Anime: <b>{data['broadcast_anime_title']}</b>\n\n"
        f"{data['broadcast_caption']}"
    )

    if data.get('broadcast_type') == 'bcast_poster' and data.get('broadcast_anime_poster'):
        await msg.answer_photo(photo=data['broadcast_anime_poster'], caption=preview_text, reply_markup=kb, parse_mode="HTML")
    else:
        await msg.answer(preview_text, reply_markup=kb, parse_mode="HTML")

    await state.set_state(BroadcastState.waiting_anime_post_confirm)


@admin_router.callback_query(F.data == "bcast_confirm")
async def broadcast_confirm_send(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return

    data = await state.get_data()
    await state.clear()

    async with AsyncSessionLocal() as session:
        news_channels = await get_news_channels(session)

    if not news_channels:
        await call.message.answer("❌ News kanallar topilmadi!")
        await call.answer()
        return

    sent = 0
    full_caption = f"🎬 <b>{data.get('broadcast_anime_title', '')}</b>\n\n{data.get('broadcast_caption', '')}"

    for ch in news_channels:
        try:
            if data.get('broadcast_type') == 'bcast_poster' and data.get('broadcast_anime_poster'):
                await call.bot.send_photo(
                    chat_id=ch.channel_id, photo=data['broadcast_anime_poster'],
                    caption=full_caption, parse_mode="HTML"
                )
            else:
                await call.bot.send_message(chat_id=ch.channel_id, text=full_caption, parse_mode="HTML")
            sent += 1
        except Exception as e:
            await call.message.answer(f"⚠️ {ch.channel_name} ga yuborishda xato: {e}")

    await call.message.answer(f"✅ {sent} ta kanalga yuborildi!", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.message(BroadcastState.waiting_content)
async def broadcast_to_users(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    await state.clear()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = result.scalars().all()

    success = 0
    failed = 0
    for user_id in user_ids:
        try:
            await msg.copy_to(chat_id=user_id)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await msg.answer(
        f"✅ Xabar yuborildi!\n\n"
        f"👤 Muvaffaqiyatli: <b>{success}</b>\n"
        f"❌ Xato: <b>{failed}</b>",
        reply_markup=admin_main_kb, parse_mode="HTML"
    )


# ====================== CHIQISH ======================

@admin_router.message(F.text == "🔙 Chiqish")
async def exit_admin(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.clear()
    await msg.answer("Admin paneldan chiqildi.", reply_markup=ReplyKeyboardRemove())