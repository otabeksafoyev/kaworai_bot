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

    # Bir xil ID tekshirish
    async with AsyncSessionLocal() as session:
        existing = await session.get(Anime, anime_id)
    if existing:
        # Boshqa ID taklif qilish
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(func.max(Anime.id)))
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
        "<i>Bu rasm inline qidiruvda thumbnail sifatida chiqadi.\n"
        "Masalan: https://i.imgur.com/abc.jpg</i>",
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
        return await msg.answer(
            "❌ URL https:// bilan boshlanishi kerak!",
            reply_markup=cancel_kb
        )
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
            poster_file_id=data['poster_file_id'],
            trailer_file_id=data.get('trailer_file_id'),
            inline_thumbnail_url=data.get('inline_thumbnail_url'),
        )
        session.add(new_anime)
        await session.commit()

    await msg.answer(
        f"✅ <b>{data['title']}</b> bazaga qo'shildi!\n\n"
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


# ====================== ANIME O'CHIRISH ======================
@admin_router.message(Command("delete_anime"))
async def delete_anime_start(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer(
        "🗑 <b>Anime o'chirish</b>\n\nAnime ID sini kiriting:",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )
    await state.set_state(EditAnime.waiting_anime_id)
    await state.update_data(action="delete")


# ====================== QISM O'CHIRISH ======================
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


# ====================== ANIME EDIT ======================
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

    # Qism o'chirish uchun maxsus format
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
                select(Series).where(
                    Series.anime_id == anime_id,
                    Series.episode == ep_num
                )
            )
            ep = result.scalar_one_or_none()
            if not ep:
                return await msg.answer(f"❌ Anime {anime_id} da {ep_num}-qism topilmadi!")
            await session.delete(ep)
            await session.commit()
        await state.clear()
        return await msg.answer(
            f"✅ {anime_id}-anime {ep_num}-qism o'chirildi!",
            reply_markup=admin_main_kb
        )

    try:
        anime_id = int(msg.text.strip())
    except ValueError:
        return await msg.answer("❌ Raqam kiriting!")

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)

    if not anime:
        return await msg.answer(f"❌ ID {anime_id} li anime topilmadi!")

    # Anime o'chirish
    if action == "delete":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, o'chirish",
                    callback_data=f"confirm_delete_{anime_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Yo'q",
                    callback_data="cancel_delete"
                )
            ]
        ])
        await state.clear()
        return await msg.answer(
            f"⚠️ <b>{anime.title}</b> animesini o'chirishni tasdiqlaysizmi?\n\n"
            f"Bu animening barcha qismlari ham o'chadi!",
            reply_markup=kb,
            parse_mode="HTML"
        )

    # Tahrirlash
    await state.update_data(edit_anime_id=anime_id)
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
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="edit_cancel")],
    ])
    await msg.answer(
        f"✏️ <b>{anime.title}</b>\n\nNimani tahrirlash kerak?",
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

    field_names = {
        "title": "yangi nomini",
        "desc": "yangi tavsifini",
        "genres": "yangi janrlarini (vergul bilan)",
        "year": "yangi yilini (raqam)",
        "poster": "yangi posterini (rasm yuboring)",
        "trailer": "yangi traylerini (video yuboring)",
        "inline_url": "yangi inline URL sini",
        "rating": "yangi reytingini (masalan: 8.5)",
    }

    await state.update_data(edit_field=field)
    await state.set_state(EditAnime.waiting_value)
    await call.message.answer(
        f"✏️ Anime {field_names.get(field, field)}ni yuboring:",
        reply_markup=cancel_kb
    )
    await call.answer()


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

        await session.commit()
        title = anime.title

    await state.clear()
    await msg.answer(
        f"✅ <b>{title}</b> yangilandi!",
        reply_markup=admin_main_kb,
        parse_mode="HTML"
    )


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
        return await msg.answer(
            "📢 <b>Hozircha kanallar yo'q.</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )

    text = "📢 <b>Kanallar ro'yxati:</b>\n\n"
    kb = InlineKeyboardBuilder()

    for ch in channels:
        status = "✅" if ch.is_active else "⛔"
        ch_type = "📰 News" if ch.is_news else ("🔒 Majburiy" if ch.require_check else "👁 Ko'rsatish")
        text += f"{status} {ch_type} — <b>{ch.channel_name}</b>\n🔗 {ch.channel_url}\n\n"
        btn_text = "⛔ Ochir" if ch.is_active else "✅ Yoq"
        kb.row(
            InlineKeyboardButton(
                text=f"{btn_text} | {ch.channel_name}",
                callback_data=f"toggle_ch_{ch.id}"
            ),
            InlineKeyboardButton(
                text="🗑 O'chirish",
                callback_data=f"del_ch_{ch.id}"
            )
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


# --- Obuna kanali qo'shish ---
@admin_router.callback_query(F.data == "add_channel")
async def start_add_channel(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    await state.set_state(AddChannel.waiting_name)
    await state.update_data(is_news_channel=False)
    await call.message.answer(
        "1️⃣ Tugmada chiqadigan <b>nom</b> kiriting:\n"
        "<i>Masalan: Anime Dunyosi, Instagram</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )
    await call.answer()


# --- News kanal qo'shish ---
@admin_router.callback_query(F.data == "add_news_channel")
async def add_news_channel_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer("❌ Admin emas!", show_alert=True)
    await state.set_state(AddChannel.waiting_name)
    await state.update_data(is_news_channel=True)
    await call.message.answer(
        "📰 <b>News kanal qo'shish</b>\n\n"
        "1️⃣ Kanal nomini kiriting:",
        parse_mode="HTML",
        reply_markup=cancel_kb
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
        "2️⃣ <b>Havola (URL)</b> kiriting:\n\n"
        "Telegram: <code>https://t.me/kanal_nomi</code>",
        parse_mode="HTML",
        reply_markup=cancel_kb
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
        return await msg.answer(
            "❌ URL https:// bilan boshlanishi kerak!",
            parse_mode="HTML",
            reply_markup=cancel_kb
        )

    data = await state.get_data()
    is_news = data.get('is_news_channel', False)
    await state.update_data(channel_url=url)

    # News kanal — bevosita ID so'rash
    if is_news:
        await state.set_state(AddChannel.waiting_channel_id)
        await msg.answer(
            "3️⃣ Telegram kanal ID sini kiriting:\n\n"
            "<i>Masalan: -1001234567890</i>\n\n"
            "📌 ID ni bilish: kanaldan xabarni @userinfobot ga forward qiling.",
            parse_mode="HTML",
            reply_markup=cancel_kb
        )
        return

    # Obuna kanali — tur tanlash
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
        parse_mode="HTML",
        reply_markup=kb
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
            session=session,
            channel_name=data["channel_name"],
            channel_url=data["channel_url"],
            require_check=False,
            is_news=False,
        )
    await call.message.edit_text(
        f"✅ <b>Kanal qo'shildi!</b>\n\n"
        f"📢 Nom: <b>{ch.channel_name}</b>\n"
        f"🔗 URL: {ch.channel_url}\n"
        f"👁 Turi: Faqat ko'rsatish",
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
        "4️⃣ Telegram kanal ID sini kiriting:\n\n"
        "<i>Masalan: -1001234567890</i>\n\n"
        "📌 ID ni bilish: @userinfobot ga forward qiling.",
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
            parse_mode="HTML",
            reply_markup=cancel_kb
        )
    data = await state.get_data()
    is_news = data.get('is_news_channel', False)
    await state.clear()

    async with AsyncSessionLocal() as session:
        ch = await add_channel(
            session=session,
            channel_name=data["channel_name"],
            channel_url=data["channel_url"],
            require_check=not is_news,
            is_news=is_news,
            channel_id=channel_id,
        )

    ch_type = "📰 News kanal" if is_news else "🔒 Majburiy obuna"
    await msg.answer(
        f"✅ <b>Kanal qo'shildi!</b>\n\n"
        f"📢 Nom: <b>{ch.channel_name}</b>\n"
        f"🔗 URL: {ch.channel_url}\n"
        f"🆔 Kanal ID: <code>{ch.channel_id}</code>\n"
        f"📌 Turi: {ch_type}",
        reply_markup=admin_main_kb,
        parse_mode="HTML"
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
    await msg.answer(
        "📢 <b>Xabar yuborish</b>\n\nNimani yubormoqchisiz?",
        reply_markup=kb,
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel_cb(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Bekor qilindi.")
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "broadcast_anime")
async def broadcast_anime_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_anime_id)
    await call.message.answer(
        "🎬 Qaysi animeni yubormoqchisiz?\n\nAnime ID sini kiriting:",
        reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(BroadcastState.waiting_anime_id)
async def broadcast_get_anime_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)
    try:
        anime_id = int(msg.text.strip())
    except ValueError:
        return await msg.answer("❌ Raqam kiriting!")

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)

    if not anime:
        return await msg.answer(f"❌ ID {anime_id} li anime topilmadi!")

    await state.update_data(broadcast_anime_id=anime_id)
    await state.set_state(BroadcastState.waiting_media_type)

    has_trailer = "✅ Treyler bor" if anime.trailer_file_id else "❌ Treyler yo'q"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Treyler bilan", callback_data="bcast_trailer")],
        [InlineKeyboardButton(text="🖼 Poster bilan", callback_data="bcast_poster")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="broadcast_cancel")],
    ])
    await msg.answer(
        f"🎬 <b>{anime.title}</b>\n"
        f"📅 Yil: {anime.year}\n"
        f"{has_trailer}\n\n"
        f"Qanday yuborilsin?",
        reply_markup=kb,
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data.in_({"bcast_trailer", "bcast_poster"}))
async def broadcast_send_anime_post(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    data = await state.get_data()
    anime_id = data['broadcast_anime_id']
    use_trailer = call.data == "bcast_trailer"

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        news_channels = await get_news_channels(session)

    if not anime:
        await state.clear()
        return await call.message.answer("❌ Anime topilmadi!", reply_markup=admin_main_kb)

    await state.clear()

    genres_text = ", ".join(anime.genres) if anime.genres else "Nomalum"
    caption = (
        f"🎌 <b>{anime.title}</b>\n\n"
        f"📅 Yil: {anime.year}\n"
        f"🎭 Janr: {genres_text}\n"
        f"⭐ Reyting: {anime.rating} ({anime.rating_count} ovoz)\n\n"
        f"📖 {anime.description}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="▶️ 1-qismni ko'rish",
            url=f"https://t.me/kaworai_uz_bot?start=anime_{anime_id}"
        )]
    ])

    if not news_channels:
        return await call.message.answer(
            "⚠️ News kanallar yo'q! Avval news kanal qo'shing.",
            reply_markup=admin_main_kb
        )

    sent_count = 0
    for ch in news_channels:
        try:
            if use_trailer and anime.trailer_file_id:
                await call.bot.send_video(
                    chat_id=ch.channel_id,
                    video=anime.trailer_file_id,
                    caption=caption,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            else:
                await call.bot.send_photo(
                    chat_id=ch.channel_id,
                    photo=anime.poster_file_id,
                    caption=caption,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            sent_count += 1
        except Exception as e:
            await call.message.answer(f"⚠️ {ch.channel_name}: {e}")

    await call.message.answer(
        f"✅ <b>{anime.title}</b> {sent_count} ta kanalga yuborildi!",
        reply_markup=admin_main_kb,
        parse_mode="HTML"
    )
    await call.answer()


@admin_router.callback_query(F.data == "broadcast_users")
async def broadcast_users_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_content)
    await call.message.answer(
        "👥 Foydalanuvchilarga yuboriladigan xabarni yuboring\n"
        "(Rasm, Video yoki Matn):",
        reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(BroadcastState.waiting_content)
async def broadcast_users_send(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor qilindi.", reply_markup=admin_main_kb)

    await state.clear()
    await msg.answer("🚀 Yuborish boshlandi...", reply_markup=admin_main_kb)

    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User.telegram_id))).scalars().all()

    count = 0
    failed = 0
    for user_id in users:
        try:
            await msg.copy_to(chat_id=user_id)
            count += 1
            await asyncio.sleep(0.05)  # Flood limitdan himoya
        except Exception:
            failed += 1

    await msg.answer(
        f"✅ Yuborildi: <b>{count}</b> kishi\n"
        f"❌ Xato: <b>{failed}</b> kishi",
        parse_mode="HTML"
    )


# ====================== CHIQISH ======================
@admin_router.message(F.text == "🔙 Chiqish")
async def exit_admin(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.clear()
    await msg.answer("Panel yopildi.", reply_markup=ReplyKeyboardRemove())