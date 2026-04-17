import asyncio
import logging
import os
from datetime import datetime, timedelta
from handlers.users import mark_admin_active, mark_admin_inactive
from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from data import config
from database.engine import AsyncSessionLocal
from database.models import Admin, Anime, RelatedContent, Series, SubscriptionChannel, User
from database.queries import add_channel, get_all_channels, get_news_channels, remove_channel, toggle_channel
from handlers.genres import GENRES, normalize_genre
from states.admin_states import AddAnime, AddChannel, AdminProState, BroadcastState, EditAnime
from utils.genre_picker import genre_picker_kb, genre_picker_text
from utils.security import esc, parse_admin_ids

logger = logging.getLogger(__name__)

admin_router = Router()

# `parse_admin_ids` bo'sh stringlarni filtrlaydi — bu muhim, chunki
# `"".split(",")` list `[""]` ni qaytaradi va bu avtorizatsiya mantig'ida
# xatolarga sabab bo'lishi mumkin.
ADMINS = parse_admin_ids(os.getenv("ADMIN_ID", ""))
SECRET_CHANNEL_ID = config.SECRET_CHANNEL_ID
NEWS_CHANNEL_ID = config.NEWS_CHANNEL_ID
BOT_USERNAME = os.getenv("BOT_USERNAME", "kaworai_uz_bot")


def _is_owner(user_id: int) -> bool:
    return str(user_id) in ADMINS


async def is_admin(user_id: int) -> bool:
    if _is_owner(user_id):
        return True
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(Admin).where(Admin.telegram_id == user_id))
        return r.scalar_one_or_none() is not None


def _yn_kb(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha", callback_data=yes_cb),
                InlineKeyboardButton(text="❌ Yo'q", callback_data=no_cb),
            ]
        ]
    )


def _skip_kb(skip_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data=skip_cb)]]
    )


def _watch_url(anime_id) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=anime_{anime_id}"


def _watch_kb(anime_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧧 Ko'rish", url=_watch_url(anime_id))]])


def _yn(val: bool) -> str:
    return "Ha" if val else "Yo'q"


def _build_post_caption(anime: Anime) -> str:
    type_emoji = {"anime": "🎌", "movie": "🎥", "serial": "📺", "dorama": "🌸"}
    emoji = type_emoji.get(anime.content_type or "anime", "🎬")
    genres_str = ", ".join((anime.genres or [])[:3]) or "—"
    tags_str = ", ".join((anime.tags or [])[:3])
    mood_str = ", ".join((anime.mood or [])[:2])
    status_map = {"completed": "✅ Tugagan", "ongoing": "📡 Davom etmoqda", "announced": "📢 Kutilmoqda"}
    status_str = status_map.get(anime.status or "", "")

    lines = [f"{emoji} <b>{anime.title}</b>" + (f" ({anime.year})" if anime.year else "")]
    lines.append(f"🎭 {genres_str}")
    if tags_str:
        lines.append(f"🏷 {tags_str}")
    if mood_str:
        lines.append(f"😌 {mood_str}")

    meta = f"⭐ {anime.rating:.1f}"
    if anime.episodes_count:
        meta += f"  🎞 {anime.episodes_count} qism"
    if anime.duration:
        meta += f"  ⏱ {anime.duration} daq"
    if status_str:
        meta += f"  {status_str}"
    lines.append(meta)
    if anime.is_pro_locked:
        lines.append("🔒 <b>Faqat Pro uchun</b>")
    desc = (anime.description or "")[:250]
    if desc:
        lines.append(f"\n📖 {desc}")
    return "\n".join(lines)


async def _send_anime_post(bot: Bot, ch, anime: Anime, msg: Message = None) -> bool:
    """Kanalga anime post yuboradi — poster + treyler."""
    caption = _build_post_caption(anime)
    watch_kb = _watch_kb(anime.id)
    try:
        if anime.poster_file_id:
            await bot.send_photo(
                chat_id=ch.channel_id,
                photo=anime.poster_file_id,
                caption=caption,
                reply_markup=watch_kb,
                parse_mode="HTML",
            )
        else:
            await bot.send_message(chat_id=ch.channel_id, text=caption, reply_markup=watch_kb, parse_mode="HTML")
        if anime.trailer_file_id:
            await bot.send_video(
                chat_id=ch.channel_id,
                video=anime.trailer_file_id,
                caption=f"🎬 <b>{anime.title}</b> — Treyler",
                parse_mode="HTML",
            )
        return True
    except Exception as e:
        if msg:
            await msg.answer(f"⚠️ {ch.channel_name} ga yuborishda xato: {e}")
        return False


# ─── Klaviaturalar ───────────────────────────────────────────────────────────

admin_main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Anime qo'shish"), KeyboardButton(text="🎞 Qism qo'shish")],
        [KeyboardButton(text="🎌 Anime boshqaruv"), KeyboardButton(text="📢 Kanal sozlamalari")],
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="✉️ Xabar yuborish")],
        [KeyboardButton(text="👑 Pro boshqaruv"), KeyboardButton(text="🏆 Top 18")],
        [KeyboardButton(text="🔙 Chiqish")],
    ],
    resize_keyboard=True,
)

cancel_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚫 Bekor qilish")]], resize_keyboard=True)

ADD_STATUS_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📡 Davom etmoqda", callback_data="addstatus_ongoing")],
        [InlineKeyboardButton(text="✅ Tugagan", callback_data="addstatus_completed")],
        [InlineKeyboardButton(text="📢 Kutilmoqda", callback_data="addstatus_announced")],
    ]
)

EDIT_STATUS_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📡 Davom etmoqda", callback_data="editstatus_ongoing")],
        [InlineKeyboardButton(text="✅ Tugagan", callback_data="editstatus_completed")],
        [InlineKeyboardButton(text="📢 Kutilmoqda", callback_data="editstatus_announced")],
    ]
)

TYPE_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🎌 Anime", callback_data="atype_anime"),
            InlineKeyboardButton(text="🎥 Kino", callback_data="atype_movie"),
        ],
        [
            InlineKeyboardButton(text="📺 Serial", callback_data="atype_serial"),
            InlineKeyboardButton(text="🌸 Dorama", callback_data="atype_dorama"),
        ],
    ]
)


# ═══════════════════════════════════════════════════════════
#  ADMIN KIRISH
# ═══════════════════════════════════════════════════════════

@admin_router.message(Command("admin"))
async def admin_entry(msg: Message, state: FSMContext):
    logger.info("admin_entry hit user_id=%s ADMINS=%s", msg.from_user.id, ADMINS)
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

    role_str = admin.role.upper() if admin else "OWNER"

    await msg.answer(
        f"🛠 <b>Kaworai Admin Panel</b>\nRol: {role_str}",
        reply_markup=admin_main_kb,
        parse_mode="HTML"
    )

    # 🔥 SHU YERGA QO‘SHASAN
    mark_admin_active(msg.from_user.id)













@admin_router.message(F.text == "🚫 Bekor qilish")
async def cancel_action(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.clear()
    await msg.answer("Amal bekor qilindi.", reply_markup=admin_main_kb)


# ═══════════════════════════════════════════════════════════
#  PRO BOSHQARUV
# ═══════════════════════════════════════════════════════════


@admin_router.message(F.text == "👑 Pro boshqaruv")
async def pro_manage_menu(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 User qidirish (ID)", callback_data="pm_user_info")],
            [InlineKeyboardButton(text="✅ Pro berish", callback_data="pm_set_pro")],
            [InlineKeyboardButton(text="❌ Pro olish", callback_data="pm_remove_pro")],
            [InlineKeyboardButton(text="⭐ Pro userlar ro'yxati", callback_data="pm_pro_list")],
            [InlineKeyboardButton(text="━━━━━━━━━━━━━━━━━", callback_data="pm_sep")],
            [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="pm_add_admin")],
            [InlineKeyboardButton(text="🗑 Admin o'chirish", callback_data="pm_remove_admin")],
            [InlineKeyboardButton(text="👥 Adminlar ro'yxati", callback_data="pm_admin_list")],
            [InlineKeyboardButton(text="━━━━━━━━━━━━━━━━━", callback_data="pm_sep")],
            [InlineKeyboardButton(text="📋 Anime info (ID)", callback_data="pm_anime_info")],
            [InlineKeyboardButton(text="📊 Pro statistika", callback_data="pm_stats")],
            [InlineKeyboardButton(text="❌ Yopish", callback_data="pm_close")],
        ]
    )
    await msg.answer("👑 <b>Pro Boshqaruv</b>", reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data == "pm_sep")
async def pm_sep(call: types.CallbackQuery):
    await call.answer()


@admin_router.callback_query(F.data == "pm_close")
async def pm_close(call: types.CallbackQuery):
    try:
        await call.message.edit_text("✅ Yopildi.")
    except Exception:
        pass
    await call.answer()


@admin_router.callback_query(F.data == "pm_user_info")
async def pm_user_info_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminProState.waiting_user_id)
    await state.update_data(pm_action="user_info")
    await call.message.answer("🔍 User ID kiriting:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.callback_query(F.data == "pm_set_pro")
async def pm_set_pro_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminProState.waiting_user_id)
    await state.update_data(pm_action="set_pro")
    await call.message.answer("✅ <b>Pro berish</b>\n\nUser ID kiriting:", parse_mode="HTML", reply_markup=cancel_kb)
    await call.answer()


@admin_router.callback_query(F.data == "pm_remove_pro")
async def pm_remove_pro_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminProState.waiting_user_id)
    await state.update_data(pm_action="remove_pro")
    await call.message.answer("❌ <b>Pro olish</b>\n\nUser ID kiriting:", parse_mode="HTML", reply_markup=cancel_kb)
    await call.answer()


@admin_router.callback_query(F.data == "pm_anime_info")
async def pm_anime_info_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminProState.waiting_user_id)
    await state.update_data(pm_action="anime_info")
    await call.message.answer("📋 Anime ID kiriting:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.callback_query(F.data == "pm_add_admin")
async def pm_add_admin_start(call: types.CallbackQuery, state: FSMContext):
    if not _is_owner(call.from_user.id):
        return await call.answer("❌ Faqat owner!", show_alert=True)
    await state.set_state(AdminProState.waiting_user_id)
    await state.update_data(pm_action="add_admin")
    await call.message.answer(
        "➕ <b>Admin qo'shish</b>\n\nUser ID kiriting:\n<i>Ixtiyoriy: ID va ism — <code>123456789 Ism</code></i>",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )
    await call.answer()


@admin_router.callback_query(F.data == "pm_remove_admin")
async def pm_remove_admin_start(call: types.CallbackQuery, state: FSMContext):
    if not _is_owner(call.from_user.id):
        return await call.answer("❌ Faqat owner!", show_alert=True)
    await state.set_state(AdminProState.waiting_user_id)
    await state.update_data(pm_action="remove_admin")
    await call.message.answer(
        "🗑 <b>Admin o'chirish</b>\n\nAdmin ID kiriting:", parse_mode="HTML", reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(AdminProState.waiting_user_id)
async def pm_id_received(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)

    data = await state.get_data()
    action = data.get("pm_action", "")
    parts = msg.text.strip().split()

    if not parts[0].isdigit():
        return await msg.answer("❌ Raqam kiriting!")

    target_id = int(parts[0])

    if action == "user_info":
        await state.clear()
        await _show_user_info(msg, target_id)

    elif action == "set_pro":
        await state.set_state(AdminProState.waiting_pro_days)
        await state.update_data(pro_target_id=target_id)
        await msg.answer(
            f"✅ User <code>{target_id}</code>\n\nNecha kun Pro? Kiriting:\n<i>30 = 30 kun, 0 = Abadiy</i>",
            parse_mode="HTML",
            reply_markup=cancel_kb,
        )

    elif action == "remove_pro":
        await state.clear()
        await _do_remove_pro(msg, target_id)

    elif action == "anime_info":
        await state.clear()
        await _show_anime_info(msg, target_id)

    elif action == "add_admin":
        if not _is_owner(msg.from_user.id):
            await state.clear()
            return await msg.answer("❌ Faqat owner!", reply_markup=admin_main_kb)
        nickname = " ".join(parts[1:]) if len(parts) > 1 else None
        await state.clear()
        await _do_add_admin(msg, target_id, nickname)

    elif action == "remove_admin":
        if not _is_owner(msg.from_user.id):
            await state.clear()
            return await msg.answer("❌ Faqat owner!", reply_markup=admin_main_kb)
        await state.clear()
        await _do_remove_admin(msg, target_id)


@admin_router.message(AdminProState.waiting_pro_days)
async def pm_pro_days_received(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.strip().isdigit():
        return await msg.answer("❌ Raqam kiriting! (0 = abadiy)")

    data = await state.get_data()
    target_id = data.get("pro_target_id")
    days = int(msg.text.strip())
    await state.clear()
    await _do_set_pro(msg, target_id, days)


async def _do_set_pro(msg: Message, user_id: int, days: int):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            return await msg.answer(f"❌ User <code>{user_id}</code> topilmadi!", parse_mode="HTML")

        now = datetime.utcnow()
        if days == 0:
            user.pro_until = None
            until_str = "Abadiy"
        else:
            base = user.pro_until if (user.pro_until and user.pro_until > now) else now
            user.pro_until = base + timedelta(days=days)
            until_str = user.pro_until.strftime("%d.%m.%Y")
        user.is_pro = True
        await session.commit()
        name = user.full_name or str(user_id)

    try:
        await msg.bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 <b>Kaworai Pro faollashtirildi!</b>\n\n📅 Tugash: <b>{until_str}</b>\n\n👉 /start → 🟢 Kaworai Pro"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await msg.answer(
        f"✅ <b>{name}</b> (<code>{user_id}</code>) Pro qilindi!\n📅 {until_str}",
        parse_mode="HTML",
        reply_markup=admin_main_kb,
    )


async def _do_remove_pro(msg: Message, user_id: int):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            return await msg.answer(f"❌ User <code>{user_id}</code> topilmadi!", parse_mode="HTML")
        user.is_pro = False
        user.pro_until = None
        await session.commit()
        name = user.full_name or str(user_id)

    try:
        await msg.bot.send_message(
            chat_id=user_id, text="❌ <b>Kaworai Pro obunangiz bekor qilindi.</b>", parse_mode="HTML"
        )
    except Exception:
        pass

    await msg.answer(
        f"✅ <b>{name}</b> (<code>{user_id}</code>) Pro olib tashlandi.", parse_mode="HTML", reply_markup=admin_main_kb
    )


async def _show_user_info(msg: Message, user_id: int):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            return await msg.answer(f"❌ User <code>{user_id}</code> topilmadi!", parse_mode="HTML")

        try:
            from database.models import AnimeSubscription

            sub_count = (
                await session.execute(
                    select(func.count(AnimeSubscription.user_id)).where(AnimeSubscription.user_id == user_id)
                )
            ).scalar() or 0
        except Exception:
            sub_count = 0

    now = datetime.utcnow()
    is_pro = user.is_pro and (not user.pro_until or user.pro_until > now)

    if user.pro_until:
        days_left = (user.pro_until - now).days
        until_full = user.pro_until.strftime("%d.%m.%Y") + f" ({days_left} kun qoldi)"
    else:
        until_full = "Abadiy" if user.is_pro else "—"

    pro_status = "✅ Ha" if is_pro else "❌ Yo'q"
    joined_str = user.joined_at.strftime("%d.%m.%Y") if user.joined_at else "—"
    # Foydalanuvchining full_name va username'i ishonchli bo'lmagan
    # matn — HTML injection'dan himoya uchun ekran qilamiz.
    username = esc(user.username) if user.username else "—"
    full_name = esc(user.full_name) if user.full_name else "—"

    text = (
        f"👤 <b>Foydalanuvchi</b>\n\n"
        f"🆔 ID: <code>{user.telegram_id}</code>\n"
        f"📛 Ism: <b>{full_name}</b>\n"
        f"🔗 @{username}\n"
        f"📅 Ro'yxatdan: {joined_str}\n\n"
        f"⭐ Pro: {pro_status}\n"
        f"📅 Pro tugashi: {until_full}\n"
        f"🔔 Obunalar: {sub_count} ta"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ 30 kun Pro", callback_data=f"adm_pro30_{user_id}"),
                InlineKeyboardButton(text="✅ 90 kun Pro", callback_data=f"adm_pro90_{user_id}"),
            ],
            [InlineKeyboardButton(text="❌ Pro olish", callback_data=f"adm_remvpro_{user_id}")],
            [
                InlineKeyboardButton(text="📉 7 kun qisq.", callback_data=f"adm_reduce7_{user_id}"),
                InlineKeyboardButton(text="📉 30 kun qisq.", callback_data=f"adm_reduce30_{user_id}"),
            ],
            [InlineKeyboardButton(text="✉️ Xabar yuborish", callback_data=f"pro_msg_{user_id}")],
        ]
    )
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("adm_pro30_"))
async def adm_pro30(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    user_id = int(call.data.replace("adm_pro30_", ""))
    await _do_set_pro_cb(call, user_id, 30)


@admin_router.callback_query(F.data.startswith("adm_pro90_"))
async def adm_pro90(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    user_id = int(call.data.replace("adm_pro90_", ""))
    await _do_set_pro_cb(call, user_id, 90)


@admin_router.callback_query(F.data.startswith("adm_remvpro_"))
async def adm_remvpro(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    user_id = int(call.data.replace("adm_remvpro_", ""))
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            return await call.answer("❌ Topilmadi!", show_alert=True)
        user.is_pro = False
        user.pro_until = None
        await session.commit()
    try:
        await call.bot.send_message(user_id, "❌ <b>Kaworai Pro bekor qilindi.</b>", parse_mode="HTML")
    except Exception:
        pass
    await call.answer("✅ Pro olib tashlandi!", show_alert=True)


@admin_router.callback_query(F.data.startswith("adm_reduce7_"))
async def adm_reduce7(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    user_id = int(call.data.replace("adm_reduce7_", ""))
    await _do_reduce_pro_cb(call, user_id, 7)


@admin_router.callback_query(F.data.startswith("adm_reduce30_"))
async def adm_reduce30(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    user_id = int(call.data.replace("adm_reduce30_", ""))
    await _do_reduce_pro_cb(call, user_id, 30)


async def _do_set_pro_cb(call: types.CallbackQuery, user_id: int, days: int):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            return await call.answer("❌ Topilmadi!", show_alert=True)
        now = datetime.utcnow()
        base = user.pro_until if (user.pro_until and user.pro_until > now) else now
        user.pro_until = base + timedelta(days=days)
        user.is_pro = True
        await session.commit()
        until_str = user.pro_until.strftime("%d.%m.%Y")
    try:
        await call.bot.send_message(
            user_id,
            f"🎉 <b>Kaworai Pro faollashtirildi!</b>\n📅 Tugash: <b>{until_str}</b>\n\n👉 /start",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer(f"✅ {days} kun Pro berildi! ({until_str})", show_alert=True)


async def _do_reduce_pro_cb(call: types.CallbackQuery, user_id: int, days: int):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.is_pro:
            return await call.answer("❌ User Pro emas!", show_alert=True)
        now = datetime.utcnow()
        if user.pro_until:
            user.pro_until = user.pro_until - timedelta(days=days)
            if user.pro_until <= now:
                user.is_pro = False
                user.pro_until = None
                res = f"Pro {days} kun qisqartirildi — tugadi."
            else:
                res = f"Pro {days} kun qisqartirildi — {user.pro_until.strftime('%d.%m.%Y')}"
        else:
            res = "Abadiy Pro ni qisqartirish mumkin emas!"
        await session.commit()
    await call.answer(res, show_alert=True)


@admin_router.callback_query(F.data == "pm_pro_list")
async def pm_pro_list(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.is_pro == True).order_by(User.pro_until.desc()))
        users = result.scalars().all()

    if not users:
        await call.answer("❌ Pro foydalanuvchilar yo'q!", show_alert=True)
        return

    now = datetime.utcnow()
    text = f"⭐ <b>Pro foydalanuvchilar ({len(users)} ta):</b>\n\n"
    for i, u in enumerate(users[:25], 1):
        uname = f"@{esc(u.username)}" if u.username else "—"
        if u.pro_until:
            days_left = (u.pro_until - now).days
            until_str = u.pro_until.strftime("%d.%m.%Y") + f" ({days_left}k)"
        else:
            until_str = "Abadiy"
        expired = " ⚠️" if (u.pro_until and u.pro_until < now) else ""
        text += f"{i}. <code>{u.telegram_id}</code> {uname} — {until_str}{expired}\n"

    try:
        await call.message.edit_text(text, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, parse_mode="HTML")
    await call.answer()


@admin_router.callback_query(F.data == "pm_admin_list")
async def pm_admin_list(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admin))
        admins = result.scalars().all()

    owner_str = ", ".join(f"<code>{o}</code>" for o in ADMINS)
    text = f"👑 <b>Ownerlar:</b> {owner_str}\n\n"

    if admins:
        text += f"🛠 <b>Adminlar ({len(admins)} ta):</b>\n\n"
        for i, a in enumerate(admins, 1):
            # Nickname odatda admin tomonidan yoziladi, lekin baribir
            # HTML injection'dan himoya uchun ekran qilamiz.
            nick = esc(a.nickname) if a.nickname else "—"
            text += f"{i}. <code>{a.telegram_id}</code> — {nick} ({esc(a.role)})\n"
    else:
        text += "🛠 Qo'shimcha adminlar yo'q."

    try:
        await call.message.edit_text(text, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, parse_mode="HTML")
    await call.answer()


async def _do_add_admin(msg: Message, new_id: int, nickname: str | None):
    if _is_owner(new_id):
        return await msg.answer("⚠️ Bu foydalanuvchi allaqachon owner!", reply_markup=admin_main_kb)

    async with AsyncSessionLocal() as session:
        existing = await session.get(Admin, new_id)
        if existing:
            return await msg.answer(
                f"⚠️ <code>{new_id}</code> allaqachon admin!", parse_mode="HTML", reply_markup=admin_main_kb
            )
        session.add(Admin(telegram_id=new_id, nickname=nickname, role="admin"))
        await session.commit()

    try:
        await msg.bot.send_message(
            new_id, "✅ <b>Siz Kaworai botiga admin qilib qo'shildingiz!</b>\n\nAdmin panel: /admin", parse_mode="HTML"
        )
    except Exception:
        pass

    nick_str = f" ({nickname})" if nickname else ""
    await msg.answer(
        f"✅ <code>{new_id}</code>{nick_str} admin qilindi!", parse_mode="HTML", reply_markup=admin_main_kb
    )


async def _do_remove_admin(msg: Message, target_id: int):
    if _is_owner(target_id):
        return await msg.answer("❌ Owner adminni o'chirib bo'lmaydi!", reply_markup=admin_main_kb)

    async with AsyncSessionLocal() as session:
        admin = await session.get(Admin, target_id)
        if not admin:
            return await msg.answer(
                f"❌ <code>{target_id}</code> admin emas!", parse_mode="HTML", reply_markup=admin_main_kb
            )
        await session.delete(admin)
        await session.commit()

    try:
        await msg.bot.send_message(target_id, "❌ <b>Admin huquqingiz olib tashlandi.</b>", parse_mode="HTML")
    except Exception:
        pass

    await msg.answer(f"✅ <code>{target_id}</code> admin emas endi.", parse_mode="HTML", reply_markup=admin_main_kb)


async def _show_anime_info(msg: Message, anime_id: int):
    from database.queries import get_anime_full_info

    async with AsyncSessionLocal() as session:
        info = await get_anime_full_info(session, anime_id)

    if not info:
        return await msg.answer(f"❌ ID {anime_id} topilmadi!")

    genres_str = ", ".join(info["genres"][:4]) or "—"
    tags_str = ", ".join(info["tags"][:4]) or "—"

    type_emoji = {"anime": "🎌", "movie": "🎥", "serial": "📺", "dorama": "🌸"}
    emoji = type_emoji.get(info["type"], "🎬")

    added_at = info.get("added_at")
    added_at_str = added_at.strftime("%d.%m.%Y %H:%M") if added_at else "Nomalum"
    year_str = f" ({info['year']})" if info.get("year") else ""

    text = (
        f"📋 <b>Anime ma'lumotlari</b>\n\n"
        f"{emoji} <b>{info['title']}</b>{year_str}\n"
        f"🆔 ID: <code>{info['id']}</code>\n"
        f"📁 Tur: {info['type']} | 📊 Status: {info.get('status', '—')}\n\n"
        f"🎭 Janr: {genres_str}\n"
        f"🏷 Teglar: {tags_str}\n\n"
        f"⭐ Reyting: <b>{info['rating']:.1f}</b> ({info['rating_count']} ovoz)\n"
        f"👁 Ko'rishlar: <b>{info['views']}</b>\n"
        f"🎞 Qismlar: <b>{info['episodes_count']}</b>\n\n"
        f"🔔 Obunalar: <b>{info['subscribers']}</b> ta\n"
        f"⭐ Pro obunalar: <b>{info['pro_subscribers']}</b> ta\n\n"
        f"🔒 Pro-locked: {_yn(info['is_pro_locked'])}\n"
        f"💎 Hidden Gem: {_yn(info['is_hidden_gem'])}\n\n"
        f"📅 Qo'shilgan: {added_at_str}"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔒 Pro-lock toggle", callback_data=f"adm_prolock_{anime_id}"),
                InlineKeyboardButton(text="💎 HGem toggle", callback_data=f"adm_hgem_{anime_id}"),
            ],
            [InlineKeyboardButton(text="📢 Kanalga post", callback_data=f"postch_all_{anime_id}")],
        ]
    )

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)

    try:
        if anime and anime.poster_file_id:
            await msg.answer_photo(photo=anime.poster_file_id, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await msg.answer(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await msg.answer(text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("adm_prolock_"))
async def adm_prolock_toggle(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    anime_id = int(call.data.replace("adm_prolock_", ""))
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if anime:
            anime.is_pro_locked = not anime.is_pro_locked
            await session.commit()
            s = "🔒 Pro-locked" if anime.is_pro_locked else "🔓 Ochiq"
            await call.answer(f"✅ {anime.title}: {s}", show_alert=True)


@admin_router.callback_query(F.data.startswith("adm_hgem_"))
async def adm_hgem_toggle(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    anime_id = int(call.data.replace("adm_hgem_", ""))
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if anime:
            anime.is_hidden_gem = not anime.is_hidden_gem
            await session.commit()
            s = "💎 Hidden Gem: Ha" if anime.is_hidden_gem else "💎 Hidden Gem: Yo'q"
            await call.answer(f"✅ {anime.title}: {s}", show_alert=True)


@admin_router.callback_query(F.data == "pm_stats")
async def pm_stats(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return

    async with AsyncSessionLocal() as session:
        total_users = await session.scalar(select(func.count(User.telegram_id)))
        pro_users = await session.scalar(select(func.count(User.telegram_id)).where(User.is_pro == True))
        total_animes = await session.scalar(select(func.count(Anime.id)))
        locked_count = await session.scalar(select(func.count(Anime.id)).where(Anime.is_pro_locked == True))
        ep_count = await session.scalar(select(func.count(Series.id)))
        now = datetime.utcnow()
        expired = await session.scalar(
            select(func.count(User.telegram_id)).where(
                User.is_pro == True, User.pro_until != None, User.pro_until < now
            )
        )
        top3 = (
            await session.execute(select(Anime.title, Anime.views).order_by(Anime.views.desc()).limit(3))
        ).fetchall()

    top3_text = "\n".join(f"  {i + 1}. {r[0]} — {r[1]} ko'rish" for i, r in enumerate(top3))
    text = (
        f"📊 <b>Pro Statistika</b>\n\n"
        f"👤 Jami: <b>{total_users}</b>\n"
        f"⭐ Pro: <b>{pro_users}</b>\n"
        f"  ⚠️ Muddati o'tgan: {expired}\n\n"
        f"🎬 Kontent: <b>{total_animes}</b>\n"
        f"  🔒 Pro-locked: {locked_count}\n"
        f"🎞 Qismlar: <b>{ep_count}</b>\n\n"
        f"🔥 Top 3:\n{top3_text}"
    )
    try:
        await call.message.edit_text(text, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, parse_mode="HTML")
    await call.answer()


@admin_router.callback_query(F.data.startswith("pro_msg_"))
async def pro_msg_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    user_id = int(call.data.replace("pro_msg_", ""))
    await state.set_state(AdminProState.waiting_msg_text)
    await state.update_data(msg_target=user_id)
    await call.message.answer(
        f"✉️ User <code>{user_id}</code> ga xabar yozing:", parse_mode="HTML", reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(AdminProState.waiting_msg_text)
async def pro_msg_send(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)

    data = await state.get_data()
    user_id = data.get("msg_target")
    await state.clear()

    prefix = "✉️ <b>Admin xabari:</b>\n\n"
    try:
        if msg.photo:
            await msg.bot.send_photo(
                user_id, msg.photo[-1].file_id, caption=prefix + (msg.caption or ""), parse_mode="HTML"
            )
        elif msg.video:
            await msg.bot.send_video(
                user_id, msg.video.file_id, caption=prefix + (msg.caption or ""), parse_mode="HTML"
            )
        else:
            await msg.bot.send_message(user_id, prefix + (msg.text or ""), parse_mode="HTML")
        await msg.answer(f"✅ Xabar yuborildi ({user_id})", reply_markup=admin_main_kb)
    except Exception as e:
        await msg.answer(f"❌ Yuborib bo'lmadi: {e}", reply_markup=admin_main_kb)


# ═══════════════════════════════════════════════════════════
#  ANIME QO'SHISH
# ═══════════════════════════════════════════════════════════


@admin_router.message(F.text == "➕ Anime qo'shish")
async def add_anime_start(msg: Message, state: FSMContext):
    logger.info("add_anime_start hit user_id=%s", msg.from_user.id)
    if not await is_admin(msg.from_user.id):
        logger.warning("add_anime_start: user %s is not admin (ADMINS=%s)", msg.from_user.id, ADMINS)
        return
    await state.set_state(AddAnime.waiting_id)
    await msg.answer(
        "🆔 Yangi kontent <b>ID</b>si (faqat raqam):\n<i>Masalan: 4345</i>", parse_mode="HTML", reply_markup=cancel_kb
    )


@admin_router.message(AddAnime.waiting_id)
async def process_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Faqat raqam!")
    anime_id = int(msg.text)
    async with AsyncSessionLocal() as session:
        if await session.get(Anime, anime_id):
            r = await session.execute(select(func.max(Anime.id)))
            sug = (r.scalar() or 0) + 1
            return await msg.answer(f"❌ ID {anime_id} mavjud!\n💡 Bo'sh ID: <code>{sug}</code>", parse_mode="HTML")
    await state.update_data(anime_id=anime_id)
    await state.set_state(AddAnime.waiting_title)
    await msg.answer("📝 <b>Nomi:</b>\n<i>Masalan: Attack on Titan</i>", parse_mode="HTML")


@admin_router.message(AddAnime.waiting_title)
async def process_title(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    await state.update_data(title=msg.text.strip())
    await state.set_state(AddAnime.waiting_type)
    await msg.answer("📁 <b>Tur:</b>", parse_mode="HTML", reply_markup=TYPE_KB)


@admin_router.callback_query(F.data.startswith("atype_"), AddAnime.waiting_type)
async def process_type(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(content_type=call.data.replace("atype_", ""))
    await state.set_state(AddAnime.waiting_desc)
    await call.message.answer(
        "📖 <b>Tavsif:</b>\n<i>Masalan: Humanity fights against giants…</i>", parse_mode="HTML", reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(AddAnime.waiting_desc)
async def process_desc(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    await state.update_data(desc=msg.text.strip(), selected_genres=[])
    await state.set_state(AddAnime.waiting_genres)
    await msg.answer(
        genre_picker_text([]),
        parse_mode="HTML",
        reply_markup=genre_picker_kb([], prefix="ag"),
    )


@admin_router.callback_query(F.data.startswith("ag_tog:"), AddAnime.waiting_genres)
async def add_genre_toggle(call: types.CallbackQuery, state: FSMContext):
    """Add anime — janrni tanlash/olib tashlash."""
    if not await is_admin(call.from_user.id):
        return await call.answer()
    key = call.data.split(":", 1)[1]
    if key not in GENRES:
        return await call.answer("❌ Noto'g'ri janr", show_alert=False)
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_genres") or [])
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(selected_genres=selected)
    try:
        await call.message.edit_text(
            genre_picker_text(selected),
            parse_mode="HTML",
            reply_markup=genre_picker_kb(selected, prefix="ag"),
        )
    except Exception:
        # Xabar o'zgartirilmasa — sodir bo'lishi mumkin, lekin baribir xatolik chiqib yiqilmasin.
        logger.debug("add_genre_toggle: edit_text failed", exc_info=True)
    await call.answer()


@admin_router.callback_query(F.data == "ag_cancel", AddAnime.waiting_genres)
async def add_genre_cancel(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    await state.clear()
    try:
        await call.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        logger.debug("add_genre_cancel: edit_text failed", exc_info=True)
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "ag_done", AddAnime.waiting_genres)
async def add_genre_done(call: types.CallbackQuery, state: FSMContext):
    """Add anime — tanlangan janrlarni tasdiqlab, keyingi bosqichga o'tish."""
    if not await is_admin(call.from_user.id):
        return await call.answer()
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_genres") or [])
    if not selected:
        return await call.answer("❌ Kamida bitta janr tanlang!", show_alert=True)
    await state.update_data(genres=selected)
    await state.set_state(AddAnime.waiting_tags)
    labels = ", ".join(GENRES.get(k, k) for k in selected)
    try:
        await call.message.edit_text(
            f"🎭 <b>Janrlar saqlandi:</b> {esc(labels)}",
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("add_genre_done: edit_text failed", exc_info=True)
    await call.message.answer(
        "🏷 <b>Teglar</b>:\n<i>dark, survival, revenge</i>",
        parse_mode="HTML",
        reply_markup=_skip_kb("skip_tags"),
    )
    await call.answer()


@admin_router.message(AddAnime.waiting_genres)
async def genres_text_hint(msg: Message, state: FSMContext):
    """Admin yozma matn yuborsa — tugmalardan foydalanishga undaydi."""
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_genres") or [])
    await msg.answer(
        "ℹ️ Iltimos, yuqoridagi tugmalar orqali janrlarni tanlang — matn bilan emas.\n" + genre_picker_text(selected),
        parse_mode="HTML",
        reply_markup=genre_picker_kb(selected, prefix="ag"),
    )


@admin_router.callback_query(F.data == "skip_tags", AddAnime.waiting_tags)
async def skip_tags(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(tags=[])
    await state.set_state(AddAnime.waiting_mood)
    await call.message.answer(
        "😌 <b>Mood</b>:\n<i>dark, emotional</i>", parse_mode="HTML", reply_markup=_skip_kb("skip_mood")
    )
    await call.answer()


@admin_router.message(AddAnime.waiting_tags)
async def process_tags(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    await state.update_data(tags=[t.strip() for t in msg.text.split(",")])
    await state.set_state(AddAnime.waiting_mood)
    await msg.answer("😌 <b>Mood</b>:\n<i>dark, emotional</i>", parse_mode="HTML", reply_markup=_skip_kb("skip_mood"))


@admin_router.callback_query(F.data == "skip_mood", AddAnime.waiting_mood)
async def skip_mood(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(mood=[])
    await state.set_state(AddAnime.waiting_year)
    await call.message.answer(
        "📅 <b>Chiqqan yili:</b>\n<i>Masalan: 2013</i>", parse_mode="HTML", reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(AddAnime.waiting_mood)
async def process_mood(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    await state.update_data(mood=[m.strip() for m in msg.text.split(",")])
    await state.set_state(AddAnime.waiting_year)
    await msg.answer("📅 <b>Chiqqan yili:</b>\n<i>Masalan: 2013</i>", parse_mode="HTML")


@admin_router.message(AddAnime.waiting_year)
async def process_year(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam!")
    await state.update_data(year=int(msg.text))
    await state.set_state(AddAnime.waiting_rating)
    await msg.answer("⭐ <b>Reyting</b> (0-10):\n<i>Masalan: 9.0</i>", parse_mode="HTML")


@admin_router.message(AddAnime.waiting_rating)
async def process_rating(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    try:
        r = float(msg.text.replace(",", "."))
        if not (0 <= r <= 10):
            return await msg.answer("❌ 0-10!")
    except ValueError:
        return await msg.answer("❌ Raqam!")
    await state.update_data(rating=r)
    await state.set_state(AddAnime.waiting_total_episodes)
    await msg.answer(
        "🎞 <b>Qismlar soni:</b>\n<i>Masalan: 25</i>", parse_mode="HTML", reply_markup=_skip_kb("skip_episodes")
    )


@admin_router.callback_query(F.data == "skip_episodes", AddAnime.waiting_total_episodes)
async def skip_episodes(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(total_episodes=0, episodes_count=0)
    await state.set_state(AddAnime.waiting_duration)
    await call.message.answer(
        "⏱ <b>Davomiyligi</b> (daqiqada):\n<i>Masalan: 24</i>",
        parse_mode="HTML",
        reply_markup=_skip_kb("skip_duration"),
    )
    await call.answer()


@admin_router.message(AddAnime.waiting_total_episodes)
async def process_total_episodes(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam!")
    ep = int(msg.text)
    await state.update_data(total_episodes=ep, episodes_count=ep)
    await state.set_state(AddAnime.waiting_duration)
    await msg.answer(
        "⏱ <b>Davomiyligi</b> (daqiqada):\n<i>Masalan: 24</i>",
        parse_mode="HTML",
        reply_markup=_skip_kb("skip_duration"),
    )


@admin_router.callback_query(F.data == "skip_duration", AddAnime.waiting_duration)
async def skip_duration(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(duration=None)
    await state.set_state(AddAnime.waiting_status)
    await call.message.answer("📊 <b>Status:</b>", parse_mode="HTML", reply_markup=ADD_STATUS_KB)
    await call.answer()


@admin_router.message(AddAnime.waiting_duration)
async def process_duration(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam!")
    await state.update_data(duration=int(msg.text))
    await state.set_state(AddAnime.waiting_status)
    await msg.answer("📊 <b>Status:</b>", parse_mode="HTML", reply_markup=ADD_STATUS_KB)


@admin_router.callback_query(F.data.startswith("addstatus_"), AddAnime.waiting_status)
async def process_add_status(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(status=call.data.replace("addstatus_", ""))
    await state.set_state(AddAnime.waiting_popularity)
    await call.message.answer(
        "📈 <b>Mashhurlik</b> (0-10):\n<i>Masalan: 8.7</i>", parse_mode="HTML", reply_markup=_skip_kb("skip_popularity")
    )
    await call.answer()


@admin_router.callback_query(F.data == "skip_popularity", AddAnime.waiting_popularity)
async def skip_popularity(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(popularity=0.0)
    await state.set_state(AddAnime.waiting_related)
    await call.message.answer(
        "🔗 <b>Related animelar</b>:\n<i>5001:sequel, 5002:spin-off</i>\n\n"
        "Format: <code>ID:tur</code> — vergul bilan ajrating",
        parse_mode="HTML",
        reply_markup=_skip_kb("skip_related"),
    )
    await call.answer()


@admin_router.message(AddAnime.waiting_popularity)
async def process_popularity(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    try:
        pop = float(msg.text.replace(",", "."))
    except ValueError:
        return await msg.answer("❌ Raqam!")
    await state.update_data(popularity=pop)
    await state.set_state(AddAnime.waiting_related)
    await msg.answer(
        "🔗 <b>Related animelar</b>:\n<i>5001:sequel, 5002:spin-off</i>",
        parse_mode="HTML",
        reply_markup=_skip_kb("skip_related"),
    )


@admin_router.callback_query(F.data == "skip_related", AddAnime.waiting_related)
async def skip_related(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(related=[])
    await state.set_state(AddAnime.waiting_pro_lock)
    await call.message.answer(
        "🔒 <b>Pro-locked?</b>", parse_mode="HTML", reply_markup=_yn_kb("prolock_yes", "prolock_no")
    )
    await call.answer()


@admin_router.message(AddAnime.waiting_related)
async def process_related(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    related = []
    for item in msg.text.split(","):
        item = item.strip()
        if ":" in item:
            parts = item.split(":", 1)
            try:
                related.append({"id": int(parts[0].strip()), "type": parts[1].strip()})
            except ValueError:
                pass
    await state.update_data(related=related)
    await state.set_state(AddAnime.waiting_pro_lock)
    await msg.answer("🔒 <b>Pro-locked?</b>", parse_mode="HTML", reply_markup=_yn_kb("prolock_yes", "prolock_no"))


@admin_router.callback_query(F.data.in_({"prolock_yes", "prolock_no"}), AddAnime.waiting_pro_lock)
async def process_pro_lock(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(is_pro_locked=(call.data == "prolock_yes"))
    await state.set_state(AddAnime.waiting_hidden_gem)
    await call.message.answer("💎 <b>Hidden Gem?</b>", parse_mode="HTML", reply_markup=_yn_kb("hgem_yes", "hgem_no"))
    await call.answer()


@admin_router.callback_query(F.data.in_({"hgem_yes", "hgem_no"}), AddAnime.waiting_hidden_gem)
async def process_hidden_gem(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(is_hidden_gem=(call.data == "hgem_yes"))
    await state.set_state(AddAnime.waiting_poster)
    await call.message.answer(
        "🖼 <b>Poster rasmini yuboring:</b>\n<i>Anime poster tasviri</i>",
        parse_mode="HTML",
        reply_markup=_skip_kb("skip_poster"),
    )
    await call.answer()


@admin_router.callback_query(F.data == "skip_poster", AddAnime.waiting_poster)
async def skip_poster(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(poster_file_id=None)
    await state.set_state(AddAnime.waiting_trailer)
    await call.message.answer("🎬 <b>Treyler videosini yuboring:</b>", reply_markup=_skip_kb("skip_trailer"))
    await call.answer()


@admin_router.message(AddAnime.waiting_poster, F.photo)
async def process_poster(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.update_data(poster_file_id=msg.photo[-1].file_id)
    await state.set_state(AddAnime.waiting_inline_url)
    await msg.answer(
        "🖼 <b>Inline thumbnail URL</b>:\n<i>https:// bilan boshlanadigan rasm URL</i>",
        parse_mode="HTML",
        reply_markup=_skip_kb("skip_inline_url"),
    )


@admin_router.callback_query(F.data == "skip_inline_url", AddAnime.waiting_inline_url)
async def skip_inline_url(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(inline_thumbnail_url=None)
    await state.set_state(AddAnime.waiting_trailer)
    await call.message.answer("🎬 <b>Treyler videosini yuboring:</b>", reply_markup=_skip_kb("skip_trailer"))
    await call.answer()


@admin_router.message(AddAnime.waiting_inline_url)
async def process_inline_url(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    url = msg.text.strip()
    if not url.startswith("http"):
        return await msg.answer("❌ https:// bilan!")
    await state.update_data(inline_thumbnail_url=url)
    await state.set_state(AddAnime.waiting_trailer)
    await msg.answer("🎬 <b>Treyler videosini yuboring:</b>", reply_markup=_skip_kb("skip_trailer"))


@admin_router.callback_query(F.data == "skip_trailer", AddAnime.waiting_trailer)
async def skip_trailer(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(trailer_file_id=None)
    await call.message.answer("⏳ Saqlanmoqda...")
    await _save_anime(call.message, state, call.bot)
    await call.answer()


@admin_router.message(AddAnime.waiting_trailer, F.video)
async def process_trailer(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.update_data(trailer_file_id=msg.video.file_id)
    await msg.answer("⏳ Saqlanmoqda...")
    await _save_anime(msg, state, msg.bot)


async def _save_anime(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    async with AsyncSessionLocal() as session:
        if await session.get(Anime, data["anime_id"]):
            return await msg.answer("❌ Bu ID allaqachon mavjud!", reply_markup=admin_main_kb)
        new_anime = Anime(
            id=data["anime_id"],
            title=data["title"],
            content_type=data.get("content_type", "anime"),
            description=data.get("desc", ""),
            genres=data.get("genres", []),
            tags=data.get("tags", []),
            mood=data.get("mood", []),
            year=data.get("year"),
            rating=data.get("rating", 0.0),
            episodes_count=data.get("episodes_count", 0),
            duration=data.get("duration"),
            status=data.get("status", "ongoing"),
            popularity=data.get("popularity", 0.0),
            is_pro_locked=data.get("is_pro_locked", False),
            is_hidden_gem=data.get("is_hidden_gem", False),
            poster_file_id=data.get("poster_file_id"),
            trailer_file_id=data.get("trailer_file_id"),
            inline_thumbnail_url=data.get("inline_thumbnail_url"),
        )
        session.add(new_anime)
        await session.flush()
        for rel in data.get("related") or []:
            rel_anime = await session.get(Anime, rel["id"])
            if rel_anime:
                session.add(
                    RelatedContent(
                        anime_id=data["anime_id"], related_id=rel["id"], relation_type=rel.get("type", "similar")
                    )
                )
        await session.commit()

    type_emoji = {"anime": "🎌", "movie": "🎥", "serial": "📺", "dorama": "🌸"}
    emoji = type_emoji.get(data.get("content_type", "anime"), "🎬")
    lock_str = "🔒 Pro" if data.get("is_pro_locked") else "🔓 Ochiq"

    # News kanalga avtomatik post so'rash
    async with AsyncSessionLocal() as session:
        news_channels = await get_news_channels(session)
        anime_obj = await session.get(Anime, data["anime_id"])

    await msg.answer(
        f"✅ {emoji} <b>{data['title']}</b> qo'shildi!\n🆔 <code>{data['anime_id']}</code> | {lock_str}",
        reply_markup=admin_main_kb,
        parse_mode="HTML",
    )

    # News kanalga yuborish so'rovi
    if news_channels and anime_obj:
        await _ask_send_to_channel(msg, bot, anime_obj)

    try:
        info = f"📋 {emoji} <b>{data['title']}</b>\n🆔 <code>{data['anime_id']}</code> | {lock_str}"
        if data.get("poster_file_id"):
            await bot.send_photo(chat_id=config.ADMIN_ID, photo=data["poster_file_id"], caption=info, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=config.ADMIN_ID, text=info, parse_mode="HTML")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  ANIME BOSHQARUV
# ═══════════════════════════════════════════════════════════


@admin_router.message(F.text == "🎌 Anime boshqaruv")
async def anime_manage_menu(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="manage_edit_anime")],
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data="manage_delete_anime")],
            [InlineKeyboardButton(text="🔒 Pro-lock toggle", callback_data="manage_pro_lock")],
            [InlineKeyboardButton(text="💎 Hidden Gem toggle", callback_data="manage_hidden_gem")],
            [InlineKeyboardButton(text="🎞 Qism oraliq o'chirish", callback_data="manage_delete_episodes")],
            [InlineKeyboardButton(text="❌ Yopish", callback_data="manage_close")],
        ]
    )
    await msg.answer("🎌 <b>Anime boshqaruv</b>", reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data == "manage_close")
async def manage_close(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.edit_text("✅ Yopildi.")
    except Exception:
        pass
    await call.answer()


@admin_router.callback_query(F.data == "manage_pro_lock")
async def manage_pro_lock_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(EditAnime.waiting_anime_id)
    await state.update_data(action="pro_lock")
    await call.message.answer("🔒 Pro-lock toggle — Anime ID:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.callback_query(F.data == "manage_hidden_gem")
async def manage_hidden_gem_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(EditAnime.waiting_anime_id)
    await state.update_data(action="hidden_gem")
    await call.message.answer("💎 Hidden Gem toggle — Anime ID:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.callback_query(F.data == "manage_edit_anime")
async def manage_edit_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(EditAnime.waiting_anime_id)
    await state.update_data(action="edit")
    await call.message.answer("✏️ Anime ID:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.callback_query(F.data == "manage_delete_anime")
async def manage_delete_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(EditAnime.waiting_delete_anime_id)
    await call.message.answer("🗑 O'chirish — Anime ID:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.message(EditAnime.waiting_delete_anime_id)
async def delete_anime_get_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam!")
    anime_id = int(msg.text)
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await msg.answer(f"❌ ID {anime_id} topilmadi!")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"confirm_delete_{anime_id}"),
                InlineKeyboardButton(text="❌ Yo'q", callback_data="cancel_delete"),
            ]
        ]
    )
    await state.clear()
    await msg.answer(f"⚠️ <b>{anime.title}</b> o'chirilsinmi?", reply_markup=kb, parse_mode="HTML")


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
            await call.message.edit_text("❌ Topilmadi!")
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "cancel_delete")
async def cancel_delete(call: types.CallbackQuery):
    try:
        await call.message.edit_text("❌ Bekor.")
    except Exception:
        pass
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.message(EditAnime.waiting_anime_id)
async def edit_get_anime(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam!")

    data = await state.get_data()
    action = data.get("action", "edit")
    anime_id = int(msg.text)

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await msg.answer(f"❌ ID {anime_id} topilmadi!")

        if action == "pro_lock":
            anime.is_pro_locked = not anime.is_pro_locked
            await session.commit()
            s = "🔒 Pro-locked" if anime.is_pro_locked else "🔓 Ochiq"
            await state.clear()
            return await msg.answer(f"✅ <b>{anime.title}</b>\n{s}", parse_mode="HTML", reply_markup=admin_main_kb)

        if action == "hidden_gem":
            anime.is_hidden_gem = not anime.is_hidden_gem
            await session.commit()
            s = "💎 Ha" if anime.is_hidden_gem else "💎 Yo'q"
            await state.clear()
            return await msg.answer(f"✅ <b>{anime.title}</b>\n{s}", parse_mode="HTML", reply_markup=admin_main_kb)

        ep_count = anime.episodes_count or 0
        title = anime.title

    await state.update_data(edit_anime_id=anime_id, edit_total_episodes=ep_count)
    await state.set_state(EditAnime.waiting_field)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Nomi", callback_data="ef_title"),
                InlineKeyboardButton(text="📖 Tavsif", callback_data="ef_desc"),
            ],
            [
                InlineKeyboardButton(text="🎭 Janr", callback_data="ef_genres"),
                InlineKeyboardButton(text="📅 Yil", callback_data="ef_year"),
            ],
            [
                InlineKeyboardButton(text="🏷 Teglar", callback_data="ef_tags"),
                InlineKeyboardButton(text="😌 Mood", callback_data="ef_mood"),
            ],
            [
                InlineKeyboardButton(text="📊 Status", callback_data="ef_status"),
                InlineKeyboardButton(text="⭐ Reyting", callback_data="ef_rating"),
            ],
            [
                InlineKeyboardButton(text="🖼 Poster", callback_data="ef_poster"),
                InlineKeyboardButton(text="🎬 Treyler", callback_data="ef_trailer"),
            ],
            [
                InlineKeyboardButton(text="🖼 Inline URL", callback_data="ef_inline_url"),
                InlineKeyboardButton(text="🔢 Qismlar soni", callback_data="ef_total_episodes"),
            ],
            [
                InlineKeyboardButton(text="🔒 Pro-lock", callback_data="ef_pro_lock"),
                InlineKeyboardButton(text="💎 Hidden Gem", callback_data="ef_hidden_gem"),
            ],
            # ── YANGI: Yashirin toggle ──────────────────────────────
            [InlineKeyboardButton(text="👁 Yashirin toggle", callback_data="ef_is_hidden")],
            # ── YANGI: Kanalga post ─────────────────────────────────
            [InlineKeyboardButton(text="📢 Kanalga post (news)", callback_data="ef_send_news")],
            [InlineKeyboardButton(text="❌ Bekor", callback_data="ef_cancel")],
        ]
    )
    await msg.answer(f"✏️ <b>{title}</b> — nimani o'zgartirasiz?", reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("ef_"), EditAnime.waiting_field)
async def edit_field_selected(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    field = call.data.replace("ef_", "")
    data = await state.get_data()
    anime_id = data.get("edit_anime_id")

    if not anime_id:
        await state.clear()
        await call.answer("❌ Xatolik.", show_alert=True)
        return

    if field == "cancel":
        await state.clear()
        try:
            await call.message.edit_text("❌ Bekor.")
        except Exception:
            pass
        await call.message.answer("Panel:", reply_markup=admin_main_kb)
        await call.answer()
        return

    # ── News kanalga post yuborish ──────────────────────────────
    if field == "send_news":
        async with AsyncSessionLocal() as session:
            anime = await session.get(Anime, anime_id)
        if anime:
            await _ask_send_to_channel(call.message, call.bot, anime)
        await state.clear()
        await call.answer()
        return

    if field == "pro_lock":
        async with AsyncSessionLocal() as session:
            anime = await session.get(Anime, anime_id)
            if anime:
                anime.is_pro_locked = not anime.is_pro_locked
                await session.commit()
                s = "🔒 Pro-locked" if anime.is_pro_locked else "🔓 Ochiq"
                await call.message.answer(f"✅ {anime.title}: {s}", reply_markup=admin_main_kb)
        await state.clear()
        await call.answer()
        return

    if field == "hidden_gem":
        async with AsyncSessionLocal() as session:
            anime = await session.get(Anime, anime_id)
            if anime:
                anime.is_hidden_gem = not anime.is_hidden_gem
                await session.commit()
                s = "💎 Ha" if anime.is_hidden_gem else "💎 Yo'q"
                await call.message.answer(f"✅ {anime.title}: {s}", reply_markup=admin_main_kb)
        await state.clear()
        await call.answer()
        return

    # ── YANGI: is_hidden (inline searchdan yashirish) ──────────
    if field == "is_hidden":
        async with AsyncSessionLocal() as session:
            anime = await session.get(Anime, anime_id)
            if anime:
                # is_hidden field yo'q bo'lsa qo'shamiz — is_pro_locked ni ishlatamiz
                # Yoki alohida field — bu yerda is_pro_locked orqali ham boshqarilishi mumkin
                # Lekin to'g'ri yo'li: model'da is_hidden field bo'lishi kerak
                # Hozircha: is_hidden_gem → "yashirin" deb ishlatamiz
                # Asl ma'nosi: inline searchda ko'rinmasin
                current = getattr(anime, "is_hidden", False)
                try:
                    anime.is_hidden = not current
                except AttributeError:
                    # Model'da field yo'q — is_hidden_gem bilan almashtirish
                    pass
                await session.commit()
                s = "👁 Yashirin: Ha" if not current else "👁 Yashirin: Yo'q"
                await call.message.answer(
                    f"✅ {anime.title}: {s}\n\n⚠️ Eslatma: <code>is_hidden</code> field'ini models.py ga qo'shing!",
                    parse_mode="HTML",
                    reply_markup=admin_main_kb,
                )
        await state.clear()
        await call.answer()
        return

    if field == "status":
        await state.update_data(edit_field="status")
        await state.set_state(EditAnime.waiting_value)
        await call.message.answer("📊 Status:", reply_markup=EDIT_STATUS_KB)
        await call.answer()
        return

    # Janrlarni tahrirlash — alohida picker orqali, matn bilan emas.
    if field == "genres":
        async with AsyncSessionLocal() as session:
            anime = await session.get(Anime, anime_id)
        current: list[str] = []
        if anime:
            from handlers.genres import parse_genres

            raw = parse_genres(anime.genres)
            seen: set[str] = set()
            for g in raw:
                k = normalize_genre(g)
                if k in GENRES and k not in seen:
                    current.append(k)
                    seen.add(k)
        await state.update_data(edit_field="genres", selected_genres=current)
        await state.set_state(EditAnime.picking_genres)
        await call.message.answer(
            genre_picker_text(current),
            parse_mode="HTML",
            reply_markup=genre_picker_kb(current, prefix="eg"),
        )
        await call.answer()
        return

    labels = {
        "title": "yangi nomini",
        "desc": "yangi tavsifini",
        "year": "yilini",
        "tags": "teglarini (vergul bilan)",
        "mood": "mood (vergul bilan)",
        "poster": "posterini (rasm yuboring)",
        "trailer": "treylerini (video yuboring)",
        "inline_url": "inline URL ni (https:// bilan)",
        "rating": "reytingini (0-10)",
        "total_episodes": "qismlar sonini",
    }
    await state.update_data(edit_field=field)
    await state.set_state(EditAnime.waiting_value)
    await call.message.answer(f"✏️ {labels.get(field, field)}ni yuboring:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.callback_query(F.data.startswith("editstatus_"), EditAnime.waiting_value)
async def edit_status_selected(call: types.CallbackQuery, state: FSMContext):
    status = call.data.replace("editstatus_", "")
    data = await state.get_data()
    anime_id = data.get("edit_anime_id")
    if not anime_id:
        await state.clear()
        return await call.answer("❌ Xatolik!", show_alert=True)
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if anime:
            anime.status = status
            await session.commit()
            title = anime.title
    await state.clear()
    await call.message.answer(f"✅ <b>{title}</b> — {status}", reply_markup=admin_main_kb, parse_mode="HTML")
    await call.answer()


@admin_router.message(EditAnime.waiting_value)
async def save_edit_value(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)

    data = await state.get_data()
    anime_id = data.get("edit_anime_id")
    field = data.get("edit_field")
    if not anime_id or not field:
        await state.clear()
        return await msg.answer("❌ Xatolik.", reply_markup=admin_main_kb)

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            await state.clear()
            return await msg.answer("❌ Topilmadi!", reply_markup=admin_main_kb)

        if field == "title":
            anime.title = msg.text.strip()
        elif field == "desc":
            anime.description = msg.text.strip()
        elif field == "tags":
            anime.tags = [t.strip() for t in msg.text.split(",")]
        elif field == "mood":
            anime.mood = [m.strip() for m in msg.text.split(",")]
        elif field == "year":
            if not msg.text.isdigit():
                return await msg.answer("❌ Raqam!")
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
                return await msg.answer("❌ https:// bilan!")
            anime.inline_thumbnail_url = url
        elif field == "rating":
            try:
                r = float(msg.text.replace(",", "."))
                if not (0 <= r <= 10):
                    return await msg.answer("❌ 0-10!")
                anime.rating = r
            except ValueError:
                return await msg.answer("❌ Raqam!")
        elif field == "total_episodes":
            if not msg.text.isdigit():
                return await msg.answer("❌ Raqam!")
            anime.episodes_count = int(msg.text)

        await session.commit()
        title = anime.title

    await state.clear()
    await msg.answer(f"✅ <b>{title}</b> yangilandi!", reply_markup=admin_main_kb, parse_mode="HTML")


# ─────────────────────────────────────────────
# Edit anime — janr picker callbacklari
# ─────────────────────────────────────────────


@admin_router.callback_query(F.data.startswith("eg_tog:"), EditAnime.picking_genres)
async def edit_genre_toggle(call: types.CallbackQuery, state: FSMContext):
    """Tahrirlash jarayonida janrni tanlash/olib tashlash."""
    if not await is_admin(call.from_user.id):
        return await call.answer()
    key = call.data.split(":", 1)[1]
    if key not in GENRES:
        return await call.answer("❌ Noto'g'ri janr", show_alert=False)
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_genres") or [])
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(selected_genres=selected)
    try:
        await call.message.edit_text(
            genre_picker_text(selected),
            parse_mode="HTML",
            reply_markup=genre_picker_kb(selected, prefix="eg"),
        )
    except Exception:
        logger.debug("edit_genre_toggle: edit_text failed", exc_info=True)
    await call.answer()


@admin_router.callback_query(F.data == "eg_cancel", EditAnime.picking_genres)
async def edit_genre_cancel(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    await state.clear()
    try:
        await call.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        logger.debug("edit_genre_cancel: edit_text failed", exc_info=True)
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "eg_done", EditAnime.picking_genres)
async def edit_genre_done(call: types.CallbackQuery, state: FSMContext):
    """Tanlangan janrlarni bazaga saqlash."""
    if not await is_admin(call.from_user.id):
        return await call.answer()
    data = await state.get_data()
    anime_id = data.get("edit_anime_id")
    selected: list[str] = list(data.get("selected_genres") or [])
    if not anime_id:
        await state.clear()
        return await call.answer("❌ Xatolik!", show_alert=True)
    if not selected:
        return await call.answer("❌ Kamida bitta janr tanlang!", show_alert=True)
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            await state.clear()
            return await call.answer("❌ Topilmadi!", show_alert=True)
        anime.genres = selected
        await session.commit()
        title = anime.title
    await state.clear()
    labels = ", ".join(GENRES.get(k, k) for k in selected)
    try:
        await call.message.edit_text(
            f"✅ <b>{esc(title)}</b> janrlari yangilandi:\n{esc(labels)}",
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("edit_genre_done: edit_text failed", exc_info=True)
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.message(EditAnime.picking_genres)
async def edit_genres_text_hint(msg: Message, state: FSMContext):
    """Admin tugma o'rniga matn yozsa — eslatma."""
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_genres") or [])
    await msg.answer(
        "ℹ️ Iltimos, yuqoridagi tugmalardan foydalaning — matn qabul qilinmaydi.\n" + genre_picker_text(selected),
        parse_mode="HTML",
        reply_markup=genre_picker_kb(selected, prefix="eg"),
    )


# ═══════════════════════════════════════════════════════════
#  NEWS KANALGA POST
# ═══════════════════════════════════════════════════════════


async def _ask_send_to_channel(msg: Message, bot: Bot, anime: Anime):
    """Bot poster/treyler bor-yo'qligiga qarab so'raydi."""
    async with AsyncSessionLocal() as session:
        channels = await get_news_channels(session)
    if not channels:
        await msg.answer("⚠️ News kanallar yo'q! Avval kanal qo'shing.")
        return

    # Poster/treyler mavjudligini tekshiramiz
    has_poster = bool(anime.poster_file_id)
    has_trailer = bool(anime.trailer_file_id)

    if not has_poster and not has_trailer:
        # Media yo'q — to'g'ridan-to'g'ri kanal tanlashga o'tish
        kb = InlineKeyboardBuilder()
        for ch in channels:
            kb.row(InlineKeyboardButton(text=f"📢 {ch.channel_name}", callback_data=f"postch_{ch.id}_{anime.id}"))
        kb.row(InlineKeyboardButton(text="📢 Barcha", callback_data=f"postch_all_{anime.id}"))
        kb.row(InlineKeyboardButton(text="❌ Bekor", callback_data="manage_close"))
        await msg.answer(
            f"📢 <b>{anime.title}</b>\n⚠️ Poster yoki treyler yo'q — faqat matn post qilinadi.\n\nQaysi kanalga?",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
        return

    # Media bor — media turi so'rash
    kb = InlineKeyboardBuilder()
    if has_poster:
        kb.row(InlineKeyboardButton(text="🖼 Poster bilan post", callback_data=f"postnews_poster_{anime.id}"))
    if has_trailer:
        kb.row(InlineKeyboardButton(text="🎬 Treyler bilan post", callback_data=f"postnews_trailer_{anime.id}"))
    kb.row(InlineKeyboardButton(text="📝 Faqat matn post", callback_data=f"postnews_text_{anime.id}"))
    kb.row(InlineKeyboardButton(text="❌ Bekor", callback_data="manage_close"))

    await msg.answer(f"📢 <b>{anime.title}</b>\n\nQanday post qilamiz?", reply_markup=kb.as_markup(), parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("postnews_"))
async def postnews_media_type(call: types.CallbackQuery):
    """Poster/treyler/text tanlov — keyin kanal tanlash."""
    if not await is_admin(call.from_user.id):
        return

    # postnews_{media_type}_{anime_id}
    parts = call.data.replace("postnews_", "").split("_", 1)
    media_type = parts[0]  # poster | trailer | text
    anime_id = int(parts[1])

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        channels = await get_news_channels(session)

    if not anime:
        return await call.answer("❌ Topilmadi!", show_alert=True)
    if not channels:
        return await call.answer("⚠️ News kanallar yo'q!", show_alert=True)

    kb = InlineKeyboardBuilder()
    for ch in channels:
        kb.row(
            InlineKeyboardButton(text=f"📢 {ch.channel_name}", callback_data=f"postch2_{media_type}_{ch.id}_{anime_id}")
        )
    kb.row(InlineKeyboardButton(text="📢 Barcha", callback_data=f"postch2_{media_type}_all_{anime_id}"))
    kb.row(InlineKeyboardButton(text="❌ Bekor", callback_data="manage_close"))

    media_label = {"poster": "🖼 Poster", "trailer": "🎬 Treyler", "text": "📝 Matn"}
    await call.message.edit_text(
        f"📢 <b>{anime.title}</b>\n{media_label.get(media_type, '')} bilan\n\nQaysi kanalga?",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )
    await call.answer()


@admin_router.callback_query(F.data.startswith("postch2_"))
async def send_to_channel_with_media(call: types.CallbackQuery):
    """Media turi va kanal tanlanib — postni yuboradi."""
    if not await is_admin(call.from_user.id):
        return

    # postch2_{media_type}_{ch_id_or_all}_{anime_id}
    raw = call.data.replace("postch2_", "")
    parts = raw.split("_")
    media_type = parts[0]
    ch_target = parts[1]
    anime_id = int(parts[2])

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        channels = await get_news_channels(session)

    if not anime:
        return await call.answer("❌ Topilmadi!", show_alert=True)

    targets = channels if ch_target == "all" else [c for c in channels if str(c.id) == ch_target]
    caption = _build_post_caption(anime)
    watch_kb = _watch_kb(anime.id)
    sent = 0

    for ch in targets:
        try:
            if media_type == "poster" and anime.poster_file_id:
                await call.bot.send_photo(
                    ch.channel_id, anime.poster_file_id, caption=caption, reply_markup=watch_kb, parse_mode="HTML"
                )
            elif media_type == "trailer" and anime.trailer_file_id:
                await call.bot.send_video(
                    ch.channel_id, anime.trailer_file_id, caption=caption, reply_markup=watch_kb, parse_mode="HTML"
                )
            else:
                await call.bot.send_message(ch.channel_id, caption, reply_markup=watch_kb, parse_mode="HTML")
            sent += 1
        except Exception as e:
            await call.message.answer(f"⚠️ {ch.channel_name}: {e}")

    try:
        await call.message.edit_text(f"✅ {sent} ta kanalga yuborildi!", parse_mode="HTML")
    except Exception:
        await call.message.answer(f"✅ {sent} ta kanalga yuborildi!")
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data.startswith("postch_"))
async def send_to_channel_cb(call: types.CallbackQuery):
    """Eski postch_ handler — matn post."""
    if not await is_admin(call.from_user.id):
        return
    parts = call.data.replace("postch_", "").split("_")
    is_all = parts[0] == "all"
    anime_id = int(parts[1])
    ch_id = None if is_all else int(parts[0])

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        channels = await get_news_channels(session)

    if not anime:
        return await call.answer("❌ Topilmadi!", show_alert=True)
    targets = channels if is_all else [c for c in channels if c.id == ch_id]
    sent = 0
    for ch in targets:
        ok = await _send_anime_post(call.bot, ch, anime, call.message)
        if ok:
            sent += 1
    try:
        await call.message.edit_text(f"✅ {sent} ta kanalga yuborildi!", parse_mode="HTML")
    except Exception:
        await call.message.answer(f"✅ {sent} ta kanalga yuborildi!")
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  XABAR YUBORISH
# ═══════════════════════════════════════════════════════════


@admin_router.message(F.text == "✉️ Xabar yuborish")
async def broadcast_start(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Anime post (kanalga)", callback_data="bc_anime_post")],
            [InlineKeyboardButton(text="🎭 Janr bo'yicha post", callback_data="bc_genre_post")],
            [InlineKeyboardButton(text="👥 Foydalanuvchilarga xabar", callback_data="bc_users")],
            [InlineKeyboardButton(text="❌ Bekor", callback_data="bc_cancel")],
        ]
    )
    await msg.answer("📢 <b>Xabar yuborish</b>", reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data == "bc_cancel")
async def bc_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.edit_text("❌ Bekor.")
    except Exception:
        pass
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "bc_anime_post")
async def bc_anime_post_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_anime_id)
    await call.message.answer("🎬 Anime ID kiriting:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.message(BroadcastState.waiting_anime_id)
async def bc_get_anime_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam!")
    anime_id = int(msg.text)
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await msg.answer(f"❌ ID {anime_id} topilmadi!")
        has_poster = bool(anime.poster_file_id)
        has_trailer = bool(anime.trailer_file_id)
        title = anime.title
        is_locked = anime.is_pro_locked

    await state.update_data(bc_anime_id=anime_id)
    await state.set_state(BroadcastState.waiting_anime_media_type)

    kb = InlineKeyboardBuilder()
    if has_poster:
        kb.row(InlineKeyboardButton(text="🖼 Poster bilan", callback_data="bcmedia_poster"))
    if has_trailer:
        kb.row(InlineKeyboardButton(text="🎬 Treyler bilan", callback_data="bcmedia_trailer"))
    kb.row(InlineKeyboardButton(text="📝 Faqat matn", callback_data="bcmedia_text"))
    kb.row(InlineKeyboardButton(text="❌ Bekor", callback_data="bc_cancel"))

    lock_str = " 🔒" if is_locked else ""
    await msg.answer(f"✅ <b>{title}</b>{lock_str}\n\nPost turi:", reply_markup=kb.as_markup(), parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("bcmedia_"), BroadcastState.waiting_anime_media_type)
async def bc_media_type_selected(call: types.CallbackQuery, state: FSMContext):
    media_type = call.data.replace("bcmedia_", "")
    await state.update_data(bc_media_type=media_type)
    await state.set_state(BroadcastState.waiting_anime_post_caption)
    data = await state.get_data()
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, data["bc_anime_id"])
    auto_cap = _build_post_caption(anime) if anime else ""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Shu caption", callback_data="bccap_auto")],
            [InlineKeyboardButton(text="✏️ O'zim yozaman", callback_data="bccap_custom")],
        ]
    )
    await call.message.answer(f"📝 <b>Caption preview:</b>\n\n{auto_cap}", reply_markup=kb, parse_mode="HTML")
    await call.answer()


@admin_router.callback_query(F.data == "bccap_auto", BroadcastState.waiting_anime_post_caption)
async def bc_caption_auto(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, data["bc_anime_id"])
    if anime:
        await state.update_data(bc_caption=_build_post_caption(anime))
    await _bc_ask_channel(call, state)
    await call.answer()


@admin_router.callback_query(F.data == "bccap_custom", BroadcastState.waiting_anime_post_caption)
async def bc_caption_custom(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("✏️ Caption yozing:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.message(BroadcastState.waiting_anime_post_caption)
async def bc_caption_received(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    await state.update_data(bc_caption=msg.text.strip())
    await state.set_state(BroadcastState.waiting_anime_post_confirm)
    async with AsyncSessionLocal() as session:
        channels = await get_news_channels(session)
    if not channels:
        await msg.answer("⚠️ News kanallar yo'q!")
        await state.clear()
        return
    kb = InlineKeyboardBuilder()
    for ch in channels:
        kb.row(InlineKeyboardButton(text=f"📢 {ch.channel_name}", callback_data=f"bcch_{ch.id}"))
    kb.row(InlineKeyboardButton(text="📢 Barcha", callback_data="bcch_all"))
    kb.row(InlineKeyboardButton(text="❌ Bekor", callback_data="bc_cancel"))
    await msg.answer("📢 Qaysi kanalga?", reply_markup=kb.as_markup())


async def _bc_ask_channel(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(BroadcastState.waiting_anime_post_confirm)
    async with AsyncSessionLocal() as session:
        channels = await get_news_channels(session)
    if not channels:
        await call.message.answer("⚠️ News kanallar yo'q!")
        await state.clear()
        return
    kb = InlineKeyboardBuilder()
    for ch in channels:
        kb.row(InlineKeyboardButton(text=f"📢 {ch.channel_name}", callback_data=f"bcch_{ch.id}"))
    kb.row(InlineKeyboardButton(text="📢 Barcha", callback_data="bcch_all"))
    kb.row(InlineKeyboardButton(text="❌ Bekor", callback_data="bc_cancel"))
    await call.message.answer("📢 Qaysi kanalga?", reply_markup=kb.as_markup())


@admin_router.callback_query(F.data.startswith("bcch_"), BroadcastState.waiting_anime_post_confirm)
async def bc_send_to_channel(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    data = await state.get_data()
    await state.clear()
    anime_id = data.get("bc_anime_id")
    caption = data.get("bc_caption", "")
    media_type = data.get("bc_media_type", "text")
    ch_target = call.data.replace("bcch_", "")

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        channels = await get_news_channels(session)

    if not anime:
        await call.answer("❌ Topilmadi!", show_alert=True)
        return
    targets = channels if ch_target == "all" else [c for c in channels if str(c.id) == ch_target]
    watch_kb = _watch_kb(anime.id)
    sent = 0

    for ch in targets:
        try:
            if media_type == "poster" and anime.poster_file_id:
                await call.bot.send_photo(
                    ch.channel_id, anime.poster_file_id, caption=caption, reply_markup=watch_kb, parse_mode="HTML"
                )
            elif media_type == "trailer" and anime.trailer_file_id:
                await call.bot.send_video(
                    ch.channel_id, anime.trailer_file_id, caption=caption, reply_markup=watch_kb, parse_mode="HTML"
                )
            else:
                await call.bot.send_message(ch.channel_id, caption, reply_markup=watch_kb, parse_mode="HTML")
            sent += 1
        except Exception as e:
            await call.message.answer(f"⚠️ {ch.channel_name}: {e}")

    try:
        await call.message.edit_text(f"✅ {sent} ta kanalga yuborildi!")
    except Exception:
        await call.message.answer(f"✅ {sent} ta kanalga yuborildi!")
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "bc_genre_post")
async def bc_genre_post_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_genre_name)
    await call.message.answer(
        "🎭 Janr nomini kiriting:\n<i>action, drama</i>", parse_mode="HTML", reply_markup=cancel_kb
    )
    await call.answer()


@admin_router.message(BroadcastState.waiting_genre_name)
async def bc_genre_name(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    genre = msg.text.strip().lower()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Anime))
        matched = [
            a
            for a in result.scalars().all()
            if a.genres and any(genre in g.lower() for g in a.genres) and not a.is_pro_locked
        ]
    if not matched:
        return await msg.answer(f"❌ {genre} janrida kontent topilmadi.")
    await state.update_data(bc_genre=genre, bc_genre_anime_ids=[a.id for a in matched])
    await state.set_state(BroadcastState.waiting_genre_channel)
    async with AsyncSessionLocal() as session:
        channels = await get_news_channels(session)
    if not channels:
        await msg.answer("⚠️ News kanallar yo'q!")
        await state.clear()
        return
    kb = InlineKeyboardBuilder()
    for ch in channels:
        kb.row(InlineKeyboardButton(text=f"📢 {ch.channel_name}", callback_data=f"bcgenrech_{ch.id}"))
    kb.row(InlineKeyboardButton(text="📢 Barcha", callback_data="bcgenrech_all"))
    kb.row(InlineKeyboardButton(text="❌ Bekor", callback_data="bc_cancel"))
    await msg.answer(f"✅ {genre} janrida {len(matched)} ta kontent\n\nQaysi kanalga?", reply_markup=kb.as_markup())


@admin_router.callback_query(F.data.startswith("bcgenrech_"), BroadcastState.waiting_genre_channel)
async def bc_genre_send(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    data = await state.get_data()
    await state.clear()
    anime_ids = data.get("bc_genre_anime_ids", [])
    ch_target = call.data.replace("bcgenrech_", "")
    async with AsyncSessionLocal() as session:
        channels = await get_news_channels(session)
        animes = [a for aid in anime_ids if (a := await session.get(Anime, aid))]
    targets = channels if ch_target == "all" else [c for c in channels if str(c.id) == ch_target]
    sent = 0
    await call.message.answer(f"⏳ {len(animes)} ta yuborilmoqda...")
    for anime in animes:
        for ch in targets:
            if await _send_anime_post(call.bot, ch, anime):
                sent += 1
        await asyncio.sleep(0.5)
    await call.message.answer(f"✅ {sent} ta post yuborildi!", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "bc_users")
async def bc_users_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_content)
    await call.message.answer("📨 Xabarni yuboring:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.message(BroadcastState.waiting_content)
async def broadcast_to_users(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    await state.clear()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = result.scalars().all()
    success = failed = 0
    for uid in user_ids:
        try:
            await msg.copy_to(chat_id=uid)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await msg.answer(
        f"✅ Yuborildi!\n👤 OK: {success}\n❌ Xato: {failed}", reply_markup=admin_main_kb, parse_mode="HTML"
    )


# ═══════════════════════════════════════════════════════════
#  QISM QO'SHISH
# ═══════════════════════════════════════════════════════════


@admin_router.message(F.text == "🎞 Qism qo'shish")
async def add_episode_start(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    await msg.answer(
        f"✅ <b>Maxfiy kanal orqali qism yuklash!</b>\n\n"
        f"Kanal ID: <code>{SECRET_CHANNEL_ID}</code>\n\n"
        "Caption format:\n<b>ID: 388\nQism: 13</b>",
        parse_mode="HTML",
    )


@admin_router.channel_post(F.chat.id == SECRET_CHANNEL_ID)
async def add_episode_from_channel(message: Message):
    if not (message.video or message.document):
        return
    caption = (message.caption or message.text or "").strip()
    file_id = message.video.file_id if message.video else message.document.file_id
    anime_id = episode = None
    for line in caption.split("\n"):
        ll = line.strip().lower()
        if ll.startswith("id:"):
            try:
                anime_id = int(line.split(":", 1)[1].strip())
            except Exception:
                pass
        elif ll.startswith(("qism:", "episode:", "part:")):
            try:
                episode = int(line.split(":", 1)[1].strip())
            except Exception:
                pass
    if anime_id is None or episode is None:
        try:
            await message.answer("❌ Format:\n<b>ID: 388\nQism: 13</b>", parse_mode="HTML")
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
        r = await session.execute(select(func.max(Series.episode)).where(Series.anime_id == anime_id))
        last_ep = r.scalar() or 0
        if episode <= last_ep:
            episode = last_ep + 1
        session.add(Series(anime_id=anime_id, episode=episode, file_id=file_id))
        await session.commit()
    try:
        await message.answer(f"✅ <b>{anime.title}</b> — {episode}-qism!", parse_mode="HTML")
    except Exception:
        pass
    try:
        await message.bot.send_message(
            config.ADMIN_ID, f"📥 <b>{anime.title}</b> — {episode}-qism qo'shildi!", parse_mode="HTML"
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  QISM O'CHIRISH
# ═══════════════════════════════════════════════════════════


@admin_router.callback_query(F.data == "manage_delete_episodes")
async def manage_delete_episodes_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(EditAnime.waiting_delete_ep_anime_id)
    await call.message.answer("🎞 Anime ID:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.message(EditAnime.waiting_delete_ep_anime_id)
async def del_ep_get_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam!")
    anime_id = int(msg.text)
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await msg.answer(f"❌ ID {anime_id} topilmadi!")
        r = await session.execute(
            select(func.min(Series.episode), func.max(Series.episode), func.count(Series.id)).where(
                Series.anime_id == anime_id
            )
        )
        min_ep, max_ep, total = r.one()
    if not total:
        return await msg.answer(f"❌ {anime.title} da qismlar yo'q!")
    await state.update_data(del_ep_anime_id=anime_id, del_ep_anime_title=anime.title)
    await state.set_state(EditAnime.waiting_delete_ep_from)
    await msg.answer(
        f"🎬 <b>{anime.title}</b>\n{min_ep}-{max_ep} (jami {total})\n\nQaysi qismdan?",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )


@admin_router.message(EditAnime.waiting_delete_ep_from)
async def del_ep_get_from(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam!")
    await state.update_data(del_ep_from=int(msg.text))
    await state.set_state(EditAnime.waiting_delete_ep_to)
    await msg.answer("Qaysi qismgacha?", reply_markup=cancel_kb)


@admin_router.message(EditAnime.waiting_delete_ep_to)
async def del_ep_get_to(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    if not msg.text.isdigit():
        return await msg.answer("❌ Raqam!")
    data = await state.get_data()
    from_ep = data["del_ep_from"]
    to_ep = int(msg.text)
    if to_ep < from_ep:
        return await msg.answer(f"❌ {to_ep} < {from_ep}!")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ {from_ep}-{to_ep} o'chir",
                    callback_data=f"delepconfirm_{data['del_ep_anime_id']}_{from_ep}_{to_ep}",
                ),
                InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_delete"),
            ]
        ]
    )
    await state.clear()
    await msg.answer(
        f"⚠️ <b>{data['del_ep_anime_title']}</b>\n{from_ep}-{to_ep} ({to_ep - from_ep + 1} ta) o'chirilsinmi?",
        reply_markup=kb,
        parse_mode="HTML",
    )


@admin_router.callback_query(F.data.startswith("delepconfirm_"))
async def confirm_del_eps(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    parts = call.data.replace("delepconfirm_", "").split("_")
    anime_id = int(parts[0])
    from_ep = int(parts[1])
    to_ep = int(parts[2])
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(Series).where(Series.anime_id == anime_id, Series.episode >= from_ep, Series.episode <= to_ep)
        )
        eps = r.scalars().all()
        for ep in eps:
            await session.delete(ep)
        await session.commit()
    await call.message.edit_text(f"✅ {from_ep}-{to_ep} ({len(eps)} ta) o'chirildi!")
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  STATISTIKA
# ═══════════════════════════════════════════════════════════


@admin_router.message(F.text == "📊 Statistika")
async def show_stats(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    async with AsyncSessionLocal() as session:
        u_count = await session.scalar(select(func.count(User.telegram_id)))
        pro_count = await session.scalar(select(func.count(User.telegram_id)).where(User.is_pro == True))
        a_count = await session.scalar(select(func.count(Anime.id)))
        locked_count = await session.scalar(select(func.count(Anime.id)).where(Anime.is_pro_locked == True))
        s_count = await session.scalar(select(func.count(Series.id)))
        ch_count = await session.scalar(select(func.count(SubscriptionChannel.id)))
    await msg.answer(
        f"📊 <b>Kaworai Statistika</b>\n\n"
        f"👤 Foydalanuvchilar: <b>{u_count}</b>\n"
        f"⭐ Pro: <b>{pro_count}</b>\n\n"
        f"🎬 Kontent: <b>{a_count}</b>\n"
        f"  🔒 Pro-locked: {locked_count}\n"
        f"🎞 Qismlar: <b>{s_count}</b>\n"
        f"📢 Kanallar: <b>{ch_count}</b>",
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════
#  TOP 18
# ═══════════════════════════════════════════════════════════


@admin_router.message(F.text == "🏆 Top 18")
async def show_top18(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    async with AsyncSessionLocal() as session:
        top_views = (await session.execute(select(Anime).order_by(Anime.views.desc()).limit(9))).scalars().all()
        top_rated = (
            (await session.execute(select(Anime).where(Anime.rating_count >= 1).order_by(Anime.rating.desc()).limit(9)))
            .scalars()
            .all()
        )

    text = "🏆 <b>TOP 18</b>\n\n👁 <b>Ko'p ko'rilgan:</b>\n"
    for i, a in enumerate(top_views, 1):
        lock = "🔒" if a.is_pro_locked else ""
        text += f"{i}. {lock}<b>{a.title}</b> — {a.views} ko'rish | ⭐{a.rating:.1f}\n"
    text += "\n⭐ <b>Yuqori reytingli:</b>\n"
    for i, a in enumerate(top_rated, 1):
        lock = "🔒" if a.is_pro_locked else ""
        text += f"{i}. {lock}<b>{a.title}</b> — ⭐{a.rating:.1f} ({a.rating_count} ovoz)\n"
    await msg.answer(text, parse_mode="HTML", reply_markup=admin_main_kb)


# ═══════════════════════════════════════════════════════════
#  KANAL SOZLAMALARI
# ═══════════════════════════════════════════════════════════


@admin_router.message(F.text == "📢 Kanal sozlamalari")
async def channel_manager(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    async with AsyncSessionLocal() as session:
        channels = await get_all_channels(session)
    if not channels:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="➕ Obuna kanali", callback_data="add_channel"),
                    InlineKeyboardButton(text="📰 News kanal", callback_data="add_news_channel"),
                ]
            ]
        )
        return await msg.answer("📢 Hozircha kanallar yo'q.", reply_markup=kb)
    text = "📢 <b>Kanallar:</b>\n\n"
    kb = InlineKeyboardBuilder()
    for ch in channels:
        st = "✅" if ch.is_active else "⛔"
        cht = "📰 News" if ch.is_news else ("🔒 Majburiy" if ch.require_check else "👁 Oddiy")
        text += f"{st} {cht} — <b>{ch.channel_name}</b>\n{ch.channel_url}\n\n"
        btn_t = "⛔ O'chir" if ch.is_active else "✅ Yoq"
        kb.row(
            InlineKeyboardButton(text=f"{btn_t} | {ch.channel_name}", callback_data=f"toggle_ch_{ch.id}"),
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del_ch_{ch.id}"),
        )
    kb.row(
        InlineKeyboardButton(text="➕ Obuna kanali", callback_data="add_channel"),
        InlineKeyboardButton(text="📰 News kanal", callback_data="add_news_channel"),
    )
    await msg.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("toggle_ch_"))
async def toggle_channel_cb(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    ch_id = int(call.data.replace("toggle_ch_", ""))
    async with AsyncSessionLocal() as session:
        result = await toggle_channel(session, ch_id)
    try:
        from middlewares.subscription import invalidate_active_channels_cache

        invalidate_active_channels_cache()
    except Exception:
        pass
    msg_text = "✅ Yoqildi" if result else "⛔ O'chirildi"
    await call.answer(msg_text, show_alert=True)
    await channel_manager(call.message)


@admin_router.callback_query(F.data.startswith("del_ch_"))
async def delete_channel_cb(call: types.CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    ch_id = int(call.data.replace("del_ch_", ""))
    async with AsyncSessionLocal() as session:
        success = await remove_channel(session, ch_id)
    if success:
        try:
            from middlewares.subscription import invalidate_active_channels_cache

            invalidate_active_channels_cache()
        except Exception:
            pass
        await call.answer("✅ O'chirildi!", show_alert=True)
        await channel_manager(call.message)
    else:
        await call.answer("❌ Topilmadi!", show_alert=True)


@admin_router.callback_query(F.data == "add_channel")
async def start_add_channel(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AddChannel.waiting_name)
    await state.update_data(is_news_channel=False)
    await call.message.answer("1️⃣ Kanal nomini kiriting:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.callback_query(F.data == "add_news_channel")
async def add_news_channel_start(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AddChannel.waiting_name)
    await state.update_data(is_news_channel=True)
    await call.message.answer("📰 News kanal nomini kiriting:", reply_markup=cancel_kb)
    await call.answer()


@admin_router.message(AddChannel.waiting_name)
async def save_ch_name(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    await state.update_data(channel_name=msg.text.strip())
    await state.set_state(AddChannel.waiting_url)
    await msg.answer("2️⃣ URL:\n<code>https://t.me/kanal</code>", parse_mode="HTML")


@admin_router.message(AddChannel.waiting_url)
async def save_ch_url(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    url = msg.text.strip()
    if not url.startswith("http"):
        return await msg.answer("❌ https:// bilan!")
    data = await state.get_data()
    is_news = data.get("is_news_channel", False)
    await state.update_data(channel_url=url)
    if is_news:
        await state.set_state(AddChannel.waiting_channel_id)
        return await msg.answer("3️⃣ Kanal ID:\n<i>-1001234567890</i>", parse_mode="HTML")
    await state.set_state(AddChannel.waiting_type)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👁 Faqat ko'rsatish", callback_data="ch_type_show")],
            [InlineKeyboardButton(text="🔒 Majburiy obuna", callback_data="ch_type_required")],
        ]
    )
    await msg.answer("3️⃣ Kanal turi:", reply_markup=kb)


@admin_router.callback_query(F.data == "ch_type_show")
async def ch_type_show(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    data = await state.get_data()
    await state.clear()
    async with AsyncSessionLocal() as session:
        ch, status = await add_channel(
            session=session,
            channel_name=data["channel_name"],
            channel_url=data["channel_url"],
            require_check=False,
            is_news=False,
        )
    if status == "created":
        text = f"✅ {esc(ch.channel_name)} qo'shildi!"
    else:
        text = f"ℹ️ {esc(ch.channel_name)} allaqachon mavjud."
    await call.message.edit_text(text, parse_mode="HTML")
    await call.message.answer("Panel:", reply_markup=admin_main_kb)
    await call.answer()


@admin_router.callback_query(F.data == "ch_type_required")
async def ch_type_required(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AddChannel.waiting_channel_id)
    await call.message.edit_text("4️⃣ Kanal ID:\n<i>-1001234567890</i>", parse_mode="HTML")
    await call.answer()


@admin_router.message(AddChannel.waiting_channel_id)
async def save_ch_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if not msg.text:
        return await msg.answer("❌ Format: <code>-1001234567890</code>", parse_mode="HTML")
    if msg.text == "🚫 Bekor qilish":
        await state.clear()
        return await msg.answer("Bekor.", reply_markup=admin_main_kb)
    try:
        channel_id = int(msg.text.strip())
    except ValueError:
        return await msg.answer("❌ Format: <code>-1001234567890</code>", parse_mode="HTML")
    data = await state.get_data()
    is_news = data.get("is_news_channel", False)
    await state.clear()
    async with AsyncSessionLocal() as session:
        ch, status = await add_channel(
            session=session,
            channel_name=data["channel_name"],
            channel_url=data["channel_url"],
            require_check=not is_news,
            is_news=is_news,
            channel_id=channel_id,
        )

    # Subscription middleware cache'ini tozalash — yangi kanal darrov paydo bo'lsin.
    try:
        from middlewares.subscription import invalidate_active_channels_cache

        invalidate_active_channels_cache()
    except Exception:
        logger.exception("save_ch_id: failed to invalidate active channels cache")

    ch_type_label = "📰 News" if is_news else "🔒 Majburiy"
    name_esc = esc(ch.channel_name)
    if status == "duplicate_mandatory":
        return await msg.answer(
            f"⚠️ <b>{name_esc}</b> allaqachon 🔒 Majburiy ro'yxatda.\n"
            f"Bir xil kanalni bitta kategoriyaga ikki marta qo'shib bo'lmaydi.",
            reply_markup=admin_main_kb,
            parse_mode="HTML",
        )
    if status == "duplicate_news":
        return await msg.answer(
            f"⚠️ <b>{name_esc}</b> allaqachon 📰 News ro'yxatda.\n"
            f"Bir xil kanalni bitta kategoriyaga ikki marta qo'shib bo'lmaydi.",
            reply_markup=admin_main_kb,
            parse_mode="HTML",
        )
    if status == "merged":
        other = "📰 News" if not is_news else "🔒 Majburiy"
        return await msg.answer(
            f"✅ <b>{name_esc}</b> ikkala kategoriyada ham faol:\n"
            f"   • {ch_type_label}  (yangi qo'shildi)\n"
            f"   • {other}  (avval bor edi)\n"
            f"🆔 <code>{ch.channel_id}</code>",
            reply_markup=admin_main_kb,
            parse_mode="HTML",
        )
    await msg.answer(
        f"✅ <b>{name_esc}</b> ({ch_type_label}) qo'shildi!\n🆔 <code>{ch.channel_id}</code>",
        reply_markup=admin_main_kb,
        parse_mode="HTML",
    )

@admin_router.message(F.text == "🔙 Chiqish")
async def exit_admin(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return

    await state.clear()

    await msg.answer(
        "Admin paneldan chiqildi.",
        reply_markup=ReplyKeyboardRemove()
    )

    # 🔥 SHU YERGA QO‘SHASAN
    mark_admin_inactive(msg.from_user.id)
