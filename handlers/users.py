"""
users.py — Kaworai Bot (to'liq versiya)

Tuzatishlar:
1. Admin panel ochiq bo'lsa — admin yozgan xabarlar o'chmasin
2. Inline tanlanganda 2-rasmdagi dizayn chiqadi
3. Baho: 1-10 tizim saqlangan
"""

import asyncio
import logging
import os
from datetime import datetime

from aiogram import F, Router, types
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaVideo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from database.engine import AsyncSessionLocal
from database.models import Anime, AnimeSubscription, Series, User
from database.queries import (
    add_or_update_rating,
    get_active_channels,
    get_or_create_user,
    get_user_rating,
    is_subscribed_anime,
)
from middlewares.subscription import check_subscription, get_sub_keyboard
from utils.regions import is_valid_region, region_label, region_picker_kb
from utils.security import parse_admin_ids

logger = logging.getLogger(__name__)

user_router = Router()
BOT_USERNAME = os.getenv("BOT_USERNAME", "kaworai_uz_bot")
PHOTO_URL = "https://i.postimg.cc/zDpjp9Mz/kawaro-(1)-(3).jpg"

GRID_SIZE = 8
GRID_COLS = 4


# ═══════════════════════════════════════════════════════════
#  ADMIN TEKSHIRISH
# ═══════════════════════════════════════════════════════════

# `parse_admin_ids` tirnoq, bo'sh stringlar va ortiqcha probellarni tozalaydi —
# Railway'da `ADMIN_ID="8173188671"` kabi qo'shtirnoqli qiymat ham to'g'ri
# tanib olinadi. Aks holda `'"8173188671"' in _ADMINS` False bo'lib, admin
# xabarlarini user_router noto'g'ri o'chirib yuborardi.
_ADMINS = set(parse_admin_ids(os.getenv("ADMIN_ID", "")))


async def _is_admin(user_id: int) -> bool:
    if str(user_id) in _ADMINS:
        return True
    try:
        from database.models import Admin

        async with AsyncSessionLocal() as session:
            r = await session.execute(select(Admin).where(Admin.telegram_id == user_id))
            return r.scalar_one_or_none() is not None
    except Exception:
        return False


# Admin panel ochiqligini tracking
_admin_panel_active: set[int] = set()


def mark_admin_active(user_id: int):
    """admin.py dagi admin_entry dan chaqiriladi."""
    _admin_panel_active.add(user_id)


def mark_admin_inactive(user_id: int):
    """admin.py dagi exit_admin dan chaqiriladi."""
    _admin_panel_active.discard(user_id)


def is_admin_panel_active(user_id: int) -> bool:
    return user_id in _admin_panel_active


# ═══════════════════════════════════════════════════════════
#  EPISODE KEYBOARD
# ═══════════════════════════════════════════════════════════


def _build_episode_keyboard(
    anime_id: int,
    all_episodes: list[int],
    current_ep: int,
    is_subscribed: bool,
    is_pro: bool,
    page: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total_eps = len(all_episodes)
    total_pages = max(1, (total_eps + GRID_SIZE - 1) // GRID_SIZE)

    start_i = page * GRID_SIZE
    end_i = min(start_i + GRID_SIZE, total_eps)
    page_eps = all_episodes[start_i:end_i]

    row_buttons = []
    for ep in page_eps:
        if ep == current_ep:
            label = f"✅ {ep} ✅"
        else:
            label = f"🟩 {ep} 🟩"
        row_buttons.append(InlineKeyboardButton(text=label, callback_data=f"ep_{anime_id}_{ep}_{page}"))
    for i in range(0, len(row_buttons), GRID_COLS):
        builder.row(*row_buttons[i : i + GRID_COLS])

    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(text="🟦 ⬅️ Oldingi", callback_data=f"eppage_{anime_id}_{current_ep}_{page - 1}")
        )
    else:
        nav_row.append(InlineKeyboardButton(text="🟦 ⬅️ Oldingi", callback_data=f"epnav_{anime_id}_{current_ep}_prev"))
    nav_row.append(InlineKeyboardButton(text=f"🟨 {page + 1} / {total_pages}", callback_data="ep_noop"))
    if page < total_pages - 1:
        nav_row.append(
            InlineKeyboardButton(text="Keyingi ➡️ 🟦", callback_data=f"eppage_{anime_id}_{current_ep}_{page + 1}")
        )
    else:
        nav_row.append(InlineKeyboardButton(text="Keyingi ➡️ 🟦", callback_data=f"epnav_{anime_id}_{current_ep}_next"))
    builder.row(*nav_row)

    share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}%3Fstart%3Danime_{anime_id}"
    builder.row(
        InlineKeyboardButton(text="🟦 Kaworai Pro", callback_data="kawaii_pass"),
        InlineKeyboardButton(text="🟪 🔗 Ulashish", url=share_url),
    )

    sub_text = "🟥 💔 Obunani bekor" if is_subscribed else "🟥 ❤️ Obuna bo'lish"
    builder.row(
        InlineKeyboardButton(text=sub_text, callback_data=f"toggle_sub_{anime_id}"),
        InlineKeyboardButton(text="🟧 ⚠️ Muammo", callback_data=f"report_ep_{anime_id}_{current_ep}"),
    )

    builder.row(
        InlineKeyboardButton(text="🟩 🏠 Menu", callback_data="main_menu"),
        InlineKeyboardButton(text="🟨 ⭐ Baho berish", callback_data=f"rate_{anime_id}"),
    )

    return builder.as_markup()


def _build_episode_caption(anime: Anime, episode: int, total_eps: int) -> str:
    type_emoji = {"anime": "🎌", "movie": "🎥", "serial": "📺", "dorama": "🌸"}
    emoji = type_emoji.get(anime.content_type or "anime", "🎬")
    return f"{emoji} <b>{anime.title}</b>\n▶ {episode}-qism  |  🎞 Jami: {total_eps} qism"


# ═══════════════════════════════════════════════════════════
#  INLINE TANLANGANDA — 2-RASMDAGI DIZAYN
# ═══════════════════════════════════════════════════════════


async def _show_anime_card_inline(message: types.Message, anime_id: int, user_id: int):
    """
    Inline dan anime tanlanganda chiqadigan karta (2-rasmdagi dizayn).

    [ Tomosha qilish (N qism)              ]
    [ ♥ obuna bo'lganlar (N) | 🔍 qidirsh ]
    [ 🏠 menu                              ]
    """
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            sent = await message.answer("❌ Kontent topilmadi!")
            await asyncio.sleep(3)
            try:
                await sent.delete()
            except Exception:
                pass
            return

        user = await session.get(User, user_id)
        now = datetime.utcnow()
        is_pro = bool(user and user.is_pro and (not user.pro_until or user.pro_until > now))

        ep_count = (
            await session.execute(select(func.count(Series.id)).where(Series.anime_id == anime_id))
        ).scalar() or 0

        sub_count = (
            await session.execute(
                select(func.count(AnimeSubscription.user_id)).where(AnimeSubscription.anime_id == anime_id)
            )
        ).scalar() or 0

        first_ep = (
            await session.execute(
                select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc()).limit(1)
            )
        ).scalar_one_or_none()

    type_emoji = {"anime": "🎌", "movie": "🎥", "serial": "📺", "dorama": "🌸"}
    emoji = type_emoji.get(anime.content_type or "anime", "🎬")
    genres_text = ", ".join((anime.genres or [])[:3]) or "Nomalum"
    tags_text = ", ".join((anime.tags or [])[:3])
    lock_str = " 🔒 Pro" if (anime.is_pro_locked and not is_pro) else ""
    status_map = {
        "completed": "✅ Tugagan",
        "ongoing": "📡 Davom etmoqda",
        "announced": "📢 Kutilmoqda",
    }
    status_str = status_map.get(anime.status or "", "")
    desc_short = (anime.description or "")[:200]

    caption = (
        f"{emoji} <b>{anime.title}</b>" + (f" ({anime.year})" if anime.year else "") + lock_str + "\n"
        f"🎭 {genres_text}\n"
        + (f"🏷 {tags_text}\n" if tags_text else "")
        + f"⭐ {anime.rating:.1f} ({anime.rating_count} ovoz)\n"
        + (f"📊 {status_str}\n" if status_str else "")
        + f"🆔 Kod: <code>{anime.id}</code>\n\n"
        + (f'📖 "{desc_short}..."' if desc_short else "")
    )

    kb_rows = []

    if anime.is_pro_locked and not is_pro:
        kb_rows.append([InlineKeyboardButton(text="🟦 Faqat Kaworai Pro uchun", callback_data="kawaii_pass")])
    elif first_ep and ep_count > 0:
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=f"🟩 Tomosha qilish ({ep_count} qism)",
                    callback_data=f"watch_start_{anime_id}",
                )
            ]
        )
    else:
        kb_rows.append([InlineKeyboardButton(text="🟧 ⏳ Qismlar hali qo'shilmagan", callback_data="no_episodes")])

    kb_rows.append(
        [
            InlineKeyboardButton(text=f"🟥 Obuna bo'lganlar ({sub_count})", callback_data="main_menu"),
            InlineKeyboardButton(text="🟨 🔍 Anime qidirish", switch_inline_query_current_chat=""),
        ]
    )

    kb_rows.append([InlineKeyboardButton(text="🟩 🏠 Menyu", callback_data="main_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    try:
        if anime.poster_file_id:
            await message.answer_photo(photo=anime.poster_file_id, caption=caption, reply_markup=kb, parse_mode="HTML")
        elif anime.inline_thumbnail_url:
            await message.answer_photo(
                photo=anime.inline_thumbnail_url, caption=caption, reply_markup=kb, parse_mode="HTML"
            )
        else:
            await message.answer(caption, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await message.answer(caption, reply_markup=kb, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════
#  ANIME KARTOCHKA (1-RASMDAGI DIZAYN)
# ═══════════════════════════════════════════════════════════


async def _show_anime_card(message: types.Message, anime_id: int, user_id: int, from_inline: bool = False):
    """
    from_inline=True  → 2-rasmdagi dizayn (inline tanlanganda)
    from_inline=False → 1-rasmdagi dizayn (kod/start orqali)
    """
    if from_inline:
        return await _show_anime_card_inline(message, anime_id, user_id)

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            sent = await message.answer("❌ Kontent topilmadi!")
            await asyncio.sleep(3)
            try:
                await sent.delete()
            except Exception:
                pass
            return

        user = await session.get(User, user_id)
        now = datetime.utcnow()
        is_pro = bool(user and user.is_pro and (not user.pro_until or user.pro_until > now))

        ep_res = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc()).limit(1)
        )
        first_ep = ep_res.scalar_one_or_none()
        subscribed = await is_subscribed_anime(session, anime_id, user_id)

    genres_text = ", ".join(anime.genres or []) or "Nomalum"
    tags_text = ", ".join((anime.tags or [])[:3])
    lock_str = " 🔒 Pro" if anime.is_pro_locked else ""
    sub_icon = "🔔" if subscribed else "🔕"
    sub_txt = "Obunani bekor qilish" if subscribed else "🔔 Obuna bo'lish"
    type_emoji = {"anime": "🎌", "movie": "🎥", "serial": "📺", "dorama": "🌸"}
    emoji = type_emoji.get(anime.content_type or "anime", "🎬")
    status_map = {
        "completed": "✅ Tugagan",
        "ongoing": "📡 Davom etmoqda",
        "announced": "📢 Kutilmoqda",
    }
    status_str = status_map.get(anime.status or "", "")
    share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}%3Fstart%3Danime_{anime_id}"

    caption = (
        f"{emoji} <b>{anime.title}</b>" + (f" ({anime.year})" if anime.year else "") + lock_str + "\n\n"
        f"🎭 {genres_text}\n"
        + (f"🏷 {tags_text}\n" if tags_text else "")
        + f"⭐ {anime.rating:.1f} ({anime.rating_count} ovoz)\n"
        + (f"📊 {status_str}\n" if status_str else "")
        + f"🆔 Kod: <code>{anime.id}</code>\n\n"
        f"📖 {(anime.description or '')[:300]}"
    )

    kb_rows = []
    if anime.is_pro_locked and not is_pro:
        kb_rows.append([InlineKeyboardButton(text="🟦 Faqat Kaworai Pro uchun", callback_data="kawaii_pass")])
    elif first_ep:
        kb_rows.append(
            [InlineKeyboardButton(text="🟩 1-qismdan tomosha qilish", callback_data=f"watch_start_{anime_id}")]
        )
        kb_rows.append([InlineKeyboardButton(text="🟩 Qismlar ro'yxati", callback_data=f"episodes_{anime_id}")])
    else:
        kb_rows.append([InlineKeyboardButton(text="⏳ Qismlar hali qo'shilmagan", callback_data="no_episodes")])

    kb_rows.append(
        [
            InlineKeyboardButton(text=f"{sub_icon} {sub_txt}", callback_data=f"toggle_sub_{anime_id}"),
            InlineKeyboardButton(text="🔗 Ulashish", url=share_url),
        ]
    )
    kb_rows.append(
        [
            InlineKeyboardButton(text="⭐ Baho berish", callback_data=f"rate_{anime_id}"),
            InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu"),
        ]
    )

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    try:
        if anime.poster_file_id:
            await message.answer_photo(photo=anime.poster_file_id, caption=caption, reply_markup=kb, parse_mode="HTML")
        elif anime.inline_thumbnail_url:
            await message.answer_photo(
                photo=anime.inline_thumbnail_url, caption=caption, reply_markup=kb, parse_mode="HTML"
            )
        else:
            await message.answer(caption, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await message.answer(caption, reply_markup=kb, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════
#  ASOSIY MENYU
# ═══════════════════════════════════════════════════════════


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟪 Janr bo'yicha", callback_data="genres"),
                InlineKeyboardButton(text="🟨 Qidiruv", switch_inline_query_current_chat=""),
            ],
            [
                InlineKeyboardButton(text="🟧 Kod orqali qidirish", callback_data="search_by_code"),
                InlineKeyboardButton(text="🟥 Obunalarim", callback_data="my_subs"),
            ],
            [
                InlineKeyboardButton(text="🟦 Kaworai Pro", callback_data="kawaii_pass"),
            ],
        ]
    )


async def send_main_menu(target, delete_prev: bool = False):
    if isinstance(target, types.CallbackQuery):
        msg = target.message
    else:
        msg = target
    caption = "🎌 <b>Kaworai Anime Botga xush kelibsiz!</b>\n\n"
    try:
        if delete_prev:
            try:
                await msg.delete()
            except Exception:
                pass
        await msg.answer_photo(
            photo=PHOTO_URL, caption=caption, reply_markup=get_main_menu_keyboard(), parse_mode="HTML"
        )
    except Exception:
        await msg.answer(caption, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")


# ═══════════════════════════════════════════════════════════
#  /start
# ═══════════════════════════════════════════════════════════


def _parse_start_anime_id(args: str) -> int | None:
    args = args or ""
    if args.startswith("anime_"):
        try:
            return int(args.replace("anime_", ""))
        except ValueError:
            return None
    if args.startswith("kod_"):
        try:
            return int(args.replace("kod_", ""))
        except ValueError:
            return None
    if args.isdigit():
        return int(args)
    return None


async def _prompt_region(message: types.Message) -> None:
    """Foydalanuvchiga viloyatni tanlatish uchun 14 viloyatli picker."""
    await message.answer(
        "👋 <b>Salom!</b>\n\nBotdan foydalanish uchun avval viloyatingizni tanlang:",
        reply_markup=region_picker_kb(callback_prefix="userregion_"),
        parse_mode="HTML",
    )


async def _continue_after_start(
    message: types.Message,
    *,
    user_id: int,
    anime_id: int | None,
    edit: bool = False,
) -> None:
    """Region tanlangan yoki oldindan bor bo'lganda — oddiy /start oqimi."""
    async with AsyncSessionLocal() as session:
        channels = await get_active_channels(session)
    not_subbed = await check_subscription(message.bot, user_id, channels)
    if not_subbed:
        kb = get_sub_keyboard(not_subbed)
        text = "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n" + "\n".join(
            f"• {ch.channel_name}" for ch in not_subbed
        )
        if edit:
            try:
                return await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass
        return await message.answer(text, reply_markup=kb, parse_mode="HTML")

    if anime_id:
        try:
            await message.delete()
        except Exception:
            pass
        await _show_anime_card(message, anime_id, user_id, from_inline=False)
        return

    await send_main_menu(message)


@user_router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(
            session=session,
            telegram_id=user_id,
            full_name=message.from_user.full_name,
            username=message.from_user.username,
        )

    anime_id = _parse_start_anime_id(command.args or "")

    # Agar region hali tanlanmagan bo'lsa — avval uni so'raymiz.
    # Anime deep-link'ni `pending_anime_id` orqali region tanlangach ochamiz.
    if not user or not is_valid_region(getattr(user, "region", None)):
        if anime_id:
            # Deep-link animeni vaqtincha user'ning o'ziga xabar sifatida eslatib
            # qo'yamiz — region tanlanganda ochiladi. Saqlash uchun oddiy
            # in-memory cache yo'q (restartga bardoshsiz), shuning uchun
            # callback_data ichida emas, lekin keyin foydalanuvchi `/start
            # anime_ID` ni qayta bossa ham ishlaydi.
            pass
        return await _prompt_region(message)

    await _continue_after_start(message, user_id=user_id, anime_id=anime_id)


@user_router.callback_query(F.data.startswith("userregion_"))
async def user_region_pick(call: types.CallbackQuery):
    """User /start'da yoki kartada 'viloyatni tanlash' tugmasidan region tanladi."""
    code = call.data.replace("userregion_", "", 1)
    if not is_valid_region(code):
        return await call.answer("❌ Noto'g'ri region!", show_alert=True)
    user_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            user = await get_or_create_user(
                session=session,
                telegram_id=user_id,
                full_name=call.from_user.full_name,
                username=call.from_user.username,
            )
        user.region = code
        await session.commit()
    try:
        await call.message.edit_text(
            f"✅ Viloyatingiz saqlandi: <b>{region_label(code)}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer("✅ Saqlandi", show_alert=False)
    await _continue_after_start(call.message, user_id=user_id, anime_id=None)


# ═══════════════════════════════════════════════════════════
#  1-QISMDAN BOSHLA
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data.startswith("watch_start_"))
async def watch_start(call: types.CallbackQuery):
    anime_id = int(call.data.replace("watch_start_", ""))
    user_id = call.from_user.id
    await call.answer()

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Topilmadi!", show_alert=True)

        user = await session.get(User, user_id)
        now = datetime.utcnow()
        is_pro = bool(user and user.is_pro and (not user.pro_until or user.pro_until > now))

        if anime.is_pro_locked and not is_pro:
            return await call.answer("🔒 Bu kontent Pro uchun!", show_alert=True)

        eps_res = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc())
        )
        episodes = eps_res.scalars().all()
        subscribed = await is_subscribed_anime(session, anime_id, user_id)

    if not episodes:
        return await call.answer("⏳ Qismlar hali qo'shilmagan!", show_alert=True)

    first_ep = episodes[0]
    ep_numbers = [e.episode for e in episodes]

    caption = _build_episode_caption(anime, first_ep.episode, len(episodes))
    kb = _build_episode_keyboard(anime_id, ep_numbers, first_ep.episode, subscribed, is_pro, page=0)

    try:
        await call.message.answer_video(
            video=first_ep.file_id,
            caption=caption,
            reply_markup=kb,
            parse_mode="HTML",
            protect_content=not is_pro,
        )
    except Exception as e:
        logger.error(f"watch_start error: {e}")
        await call.message.answer(caption, reply_markup=kb, parse_mode="HTML")

    try:
        from database.queries import add_to_watch_history, record_view

        async with AsyncSessionLocal() as session:
            await add_to_watch_history(session, user_id, anime_id, episode=first_ep.episode)
            await record_view(session, anime_id, user_id)
    except Exception as e:
        logger.error(f"watch_start history error: {e}")


# ═══════════════════════════════════════════════════════════
#  QISM TANLASH (GRID)
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data.startswith("ep_") & ~F.data.startswith("eppage_") & ~F.data.startswith("epnav_"))
async def episode_select(call: types.CallbackQuery):
    if call.data == "ep_noop":
        return await call.answer()

    parts = call.data.split("_")
    if len(parts) < 4:
        return await call.answer()

    try:
        anime_id = int(parts[1])
        episode = int(parts[2])
        page = int(parts[3])
    except (ValueError, IndexError):
        return await call.answer("❌ Xatolik!", show_alert=True)

    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Topilmadi!", show_alert=True)

        user = await session.get(User, user_id)
        now = datetime.utcnow()
        is_pro = bool(user and user.is_pro and (not user.pro_until or user.pro_until > now))

        if anime.is_pro_locked and not is_pro:
            return await call.answer("🔒 Bu kontent Pro uchun!", show_alert=True)

        ep_res = await session.execute(select(Series).where(Series.anime_id == anime_id, Series.episode == episode))
        ep_obj = ep_res.scalar_one_or_none()
        if not ep_obj:
            return await call.answer(f"❌ {episode}-qism topilmadi!", show_alert=True)

        all_eps_res = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc())
        )
        all_episodes = [e.episode for e in all_eps_res.scalars().all()]
        subscribed = await is_subscribed_anime(session, anime_id, user_id)

    caption = _build_episode_caption(anime, episode, len(all_episodes))
    kb = _build_episode_keyboard(anime_id, all_episodes, episode, subscribed, is_pro, page=page)

    await call.answer()

    try:
        await call.message.edit_media(
            media=InputMediaVideo(media=ep_obj.file_id, caption=caption, parse_mode="HTML"),
            reply_markup=kb,
        )
    except Exception as e:
        logger.warning(f"edit_media failed: {e}")
        try:
            await call.message.answer_video(
                video=ep_obj.file_id,
                caption=caption,
                reply_markup=kb,
                parse_mode="HTML",
                protect_content=not is_pro,
            )
        except Exception as e2:
            logger.error(f"episode_select fallback: {e2}")

    try:
        from database.queries import add_to_watch_history, record_view

        async with AsyncSessionLocal() as session:
            await add_to_watch_history(session, user_id, anime_id, episode=episode)
            await record_view(session, anime_id, user_id)
    except Exception as e:
        logger.error(f"episode_select history: {e}")


# ═══════════════════════════════════════════════════════════
#  GRID SAHIFA
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data.startswith("eppage_"))
async def episode_page_change(call: types.CallbackQuery):
    parts = call.data.split("_")
    try:
        anime_id = int(parts[1])
        current_ep = int(parts[2])
        new_page = int(parts[3])
    except (ValueError, IndexError):
        return await call.answer()

    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Topilmadi!", show_alert=True)

        user = await session.get(User, user_id)
        now = datetime.utcnow()
        is_pro = bool(user and user.is_pro and (not user.pro_until or user.pro_until > now))

        all_eps_res = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc())
        )
        all_episodes = [e.episode for e in all_eps_res.scalars().all()]
        subscribed = await is_subscribed_anime(session, anime_id, user_id)

    kb = _build_episode_keyboard(anime_id, all_episodes, current_ep, subscribed, is_pro, page=new_page)
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=kb)
    except Exception as e:
        logger.warning(f"eppage error: {e}")


# ═══════════════════════════════════════════════════════════
#  OLDINGI / KEYINGI QISM
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data.startswith("epnav_"))
async def episode_navigate(call: types.CallbackQuery):
    parts = call.data.split("_")
    try:
        anime_id = int(parts[1])
        current_ep = int(parts[2])
        direction = parts[3]
    except (ValueError, IndexError):
        return await call.answer()

    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Topilmadi!", show_alert=True)

        user = await session.get(User, user_id)
        now = datetime.utcnow()
        is_pro = bool(user and user.is_pro and (not user.pro_until or user.pro_until > now))

        if anime.is_pro_locked and not is_pro:
            return await call.answer("🔒 Bu kontent Pro uchun!", show_alert=True)

        all_eps_res = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc())
        )
        all_eps = all_eps_res.scalars().all()
        ep_numbers = [e.episode for e in all_eps]

        if not ep_numbers:
            return await call.answer("❌ Qismlar yo'q!", show_alert=True)

        try:
            idx = ep_numbers.index(current_ep)
        except ValueError:
            idx = 0

        if direction == "prev":
            if idx == 0:
                return await call.answer("⛔ Bu birinchi qism!", show_alert=True)
            new_idx = idx - 1
        else:
            if idx >= len(ep_numbers) - 1:
                return await call.answer("✅ Bu oxirgi qism!", show_alert=True)
            new_idx = idx + 1

        new_ep_num = ep_numbers[new_idx]
        new_ep_obj = all_eps[new_idx]
        new_page = new_idx // GRID_SIZE
        subscribed = await is_subscribed_anime(session, anime_id, user_id)

    caption = _build_episode_caption(anime, new_ep_num, len(ep_numbers))
    kb = _build_episode_keyboard(anime_id, ep_numbers, new_ep_num, subscribed, is_pro, page=new_page)

    await call.answer()

    try:
        await call.message.edit_media(
            media=InputMediaVideo(media=new_ep_obj.file_id, caption=caption, parse_mode="HTML"),
            reply_markup=kb,
        )
    except Exception as e:
        logger.warning(f"epnav error: {e}")
        try:
            await call.message.answer_video(
                video=new_ep_obj.file_id,
                caption=caption,
                reply_markup=kb,
                parse_mode="HTML",
                protect_content=not is_pro,
            )
        except Exception as e2:
            logger.error(f"epnav fallback: {e2}")

    try:
        from database.queries import add_to_watch_history, record_view

        async with AsyncSessionLocal() as session:
            is_completed = new_idx == len(ep_numbers) - 1
            await add_to_watch_history(session, user_id, anime_id, episode=new_ep_num, is_completed=is_completed)
            await record_view(session, anime_id, user_id)
    except Exception as e:
        logger.error(f"epnav history: {e}")


# ═══════════════════════════════════════════════════════════
#  QISMLAR RO'YXATI
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data.startswith("episodes_"))
async def show_episodes_list(call: types.CallbackQuery):
    anime_id = int(call.data.replace("episodes_", ""))
    user_id = call.from_user.id
    await call.answer()

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Topilmadi!", show_alert=True)

        user = await session.get(User, user_id)
        now = datetime.utcnow()
        is_pro = bool(user and user.is_pro and (not user.pro_until or user.pro_until > now))

        if anime.is_pro_locked and not is_pro:
            return await call.answer("🔒 Bu kontent Pro uchun!", show_alert=True)

        eps_res = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc())
        )
        episodes = eps_res.scalars().all()
        subscribed = await is_subscribed_anime(session, anime_id, user_id)

    if not episodes:
        return await call.answer("⏳ Qismlar hali qo'shilmagan!", show_alert=True)

    first_ep = episodes[0]
    ep_numbers = [e.episode for e in episodes]

    caption = _build_episode_caption(anime, first_ep.episode, len(episodes))
    kb = _build_episode_keyboard(anime_id, ep_numbers, first_ep.episode, subscribed, is_pro, page=0)

    try:
        await call.message.answer_video(
            video=first_ep.file_id,
            caption=caption,
            reply_markup=kb,
            parse_mode="HTML",
            protect_content=not is_pro,
        )
    except Exception as e:
        logger.error(f"show_episodes_list error: {e}")
        await call.message.answer(caption, reply_markup=kb, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════
#  OBUNA TOGGLE
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data.startswith("toggle_sub_"))
async def toggle_subscription(call: types.CallbackQuery):
    anime_id = int(call.data.replace("toggle_sub_", ""))
    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        from database.queries import subscribe_anime, unsubscribe_anime

        already = await is_subscribed_anime(session, anime_id, user_id)
        if already:
            await unsubscribe_anime(session, anime_id, user_id)
            await call.answer("🔕 Obuna bekor qilindi!", show_alert=True)
        else:
            await subscribe_anime(session, anime_id, user_id)
            await call.answer("🔔 Obuna bo'ldingiz!", show_alert=True)

        anime = await session.get(Anime, anime_id)
        user = await session.get(User, user_id)
        now = datetime.utcnow()
        is_pro = bool(user and user.is_pro and (not user.pro_until or user.pro_until > now))

        all_eps_res = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc())
        )
        all_episodes = [e.episode for e in all_eps_res.scalars().all()]
        new_subscribed = not already

    current_ep = 1
    if call.message.caption:
        try:
            for part in call.message.caption.split("\n"):
                if "qism" in part and "▶" in part:
                    current_ep = int(part.split("▶")[1].split("-")[0].strip())
                    break
        except Exception:
            pass

    if all_episodes and anime:
        page = all_episodes.index(current_ep) // GRID_SIZE if current_ep in all_episodes else 0
        kb = _build_episode_keyboard(anime_id, all_episodes, current_ep, new_subscribed, is_pro, page=page)
        try:
            await call.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#  MUAMMO
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data.startswith("report_ep_"))
async def report_episode(call: types.CallbackQuery):
    parts = call.data.replace("report_ep_", "").split("_")
    try:
        anime_id = int(parts[0])
        episode = int(parts[1])
    except (ValueError, IndexError):
        return await call.answer()

    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        title = anime.title if anime else f"ID {anime_id}"

    try:
        admin_id = os.getenv("ADMIN_ID", "").split(",")[0]
        if admin_id:
            await call.bot.send_message(
                chat_id=int(admin_id),
                text=(
                    f"⚠️ <b>Muammo xabari</b>\n\n"
                    f"🎬 Kontent: <b>{title}</b>\n"
                    f"🆔 ID: <code>{anime_id}</code>\n"
                    f"📺 Qism: <b>{episode}</b>\n"
                    f"👤 User: <code>{user_id}</code>"
                ),
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"report_episode error: {e}")

    await call.answer("⚠️ Muammo yuborildi! Tez orada hal qilinadi.", show_alert=True)


# ═══════════════════════════════════════════════════════════
#  BAHO BERISH — 1 DAN 10 GACHA
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(
    F.data.startswith("rate_") & ~F.data.startswith("rate_set_") & ~F.data.startswith("rate_cancel")
)
async def rate_anime_start(call: types.CallbackQuery):
    anime_id = int(call.data.replace("rate_", ""))

    async with AsyncSessionLocal() as session:
        existing = await get_user_rating(session, anime_id, call.from_user.id)

    if existing:
        return await call.answer(f"✅ Siz allaqachon baho bergansiz: {existing.score}/10", show_alert=True)

    rows = []
    row = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f"rate_set_{anime_id}_{i}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="❌ Bekor", callback_data="rate_cancel")])

    await call.answer()
    await call.message.answer(
        "⭐ <b>Anime uchun baho bering (1-10):</b>\n\n1 = Yomon  |  5 = O'rtacha  |  10 = A'lo",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )


@user_router.callback_query(F.data.startswith("rate_set_"))
async def rate_anime_set(call: types.CallbackQuery):
    parts = call.data.replace("rate_set_", "").split("_")
    try:
        anime_id = int(parts[0])
        score = int(parts[1])
    except (ValueError, IndexError):
        return await call.answer()

    async with AsyncSessionLocal() as session:
        existing = await get_user_rating(session, anime_id, call.from_user.id)
        if existing:
            return await call.answer(f"✅ Siz allaqachon baho bergansiz: {existing.score}/10", show_alert=True)
        new_avg = await add_or_update_rating(session, anime_id, call.from_user.id, score)
        anime = await session.get(Anime, anime_id)

    title = anime.title if anime else f"ID {anime_id}"
    try:
        await call.message.edit_text(
            f"✅ <b>Baho qabul qilindi!</b>\n\n"
            f"🎬 <b>{title}</b>\n"
            f"⭐ Sizning bahoyingiz: <b>{score}/10</b>\n"
            f"📊 O'rtacha reyting: <b>{new_avg}/10</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer(f"⭐ {score}/10 — Rahmat!", show_alert=True)


@user_router.callback_query(F.data == "rate_cancel")
async def rate_cancel(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  ASOSIY MENYU CALLBACK
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data == "main_menu")
async def go_main_menu(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    await send_main_menu(call.message)


@user_router.callback_query(F.data == "no_episodes")
async def no_episodes_cb(call: types.CallbackQuery):
    await call.answer("⏳ Qismlar hali qo'shilmagan!", show_alert=True)


@user_router.callback_query(F.data == "ep_noop")
async def ep_noop(call: types.CallbackQuery):
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  KOD ORQALI QIDIRISH
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data == "search_by_code")
async def search_by_code_cb(call: types.CallbackQuery):
    text = (
        "🔢 <b>Kod orqali qidirish</b>\n\n"
        "Anime kodini (ID) yuboring.\n"
        "<i>Kod inline qidiruv natijasida ko'rinadi.</i>\n\n"
        "Masalan: <code>388</code>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")]]
    )
    try:
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await call.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


@user_router.message(F.text.regexp(r"^\d+$"))
async def handle_code_input(message: types.Message):
    user_id = message.from_user.id
    anime_id = int(message.text.strip())
    try:
        await message.delete()
    except Exception:
        pass
    async with AsyncSessionLocal() as session:
        channels = await get_active_channels(session)
    not_subbed = await check_subscription(message.bot, user_id, channels)
    if not_subbed:
        return
    # Kod orqali → 1-rasmdagi dizayn
    await _show_anime_card(message, anime_id, user_id, from_inline=False)


# ═══════════════════════════════════════════════════════════
#  OBUNALARIM
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data == "my_subs")
async def my_subscriptions(call: types.CallbackQuery):
    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AnimeSubscription)
            .where(AnimeSubscription.user_id == user_id)
            .order_by(AnimeSubscription.created_at.desc())
        )
        subs = result.scalars().all()
        anime_list = []
        for sub in subs:
            anime = await session.get(Anime, sub.anime_id)
            if anime:
                anime_list.append(anime)

    if not anime_list:
        text = (
            "🔕 <b>Obunalarim</b>\n\n"
            "Siz hozircha hech qaysi animega obuna bo'lmagansiz.\n\n"
            "Anime sahifasidagi 🔔 <b>Obuna bo'lish</b> tugmasini bosing."
        )
        rows = [[InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")]]
    else:
        text = f"🔔 <b>Mening obunalarim ({len(anime_list)} ta):</b>\n\n"
        rows = []
        for anime in anime_list[:15]:
            lock = "🔒 " if anime.is_pro_locked else ""
            text += f"🎬 {lock}{anime.title}\n"
            rows.append([InlineKeyboardButton(text=f"🎬 {lock}{anime.title}", callback_data=f"anime_info_{anime.id}")])
        rows.append([InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")])

    kb_markup = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await call.message.edit_caption(caption=text, reply_markup=kb_markup, parse_mode="HTML")
    except Exception:
        try:
            await call.message.edit_text(text=text, reply_markup=kb_markup, parse_mode="HTML")
        except Exception:
            await call.message.answer(text, reply_markup=kb_markup, parse_mode="HTML")
    await call.answer()


@user_router.callback_query(F.data.startswith("anime_info_"))
async def anime_info_cb(call: types.CallbackQuery):
    anime_id = int(call.data.replace("anime_info_", ""))
    await call.answer()
    await _show_anime_card(call.message, anime_id, call.from_user.id, from_inline=False)


# ═══════════════════════════════════════════════════════════
#  OBUNA TEKSHIRISH
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data == "check_subs")
async def recheck_subscription(call: types.CallbackQuery):
    user_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        channels = await get_active_channels(session)
    not_subbed = await check_subscription(call.bot, user_id, channels)
    if not_subbed:
        kb = get_sub_keyboard(not_subbed)
        try:
            await call.message.edit_text(
                "❌ <b>Siz hali barcha kanallarga obuna bo'lmagansiz!</b>\n\n"
                + "\n".join(f"• {ch.channel_name}" for ch in not_subbed),
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception:
            pass
        await call.answer("❌ Hali to'liq obuna emassiz!", show_alert=True)
    else:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_main_menu(call.message)
        await call.answer("✅ Obuna tasdiqlandi!", show_alert=True)


@user_router.callback_query(F.data == "cancel_sub_check")
async def cancel_sub(call: types.CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  MEDIA BLOKLASH
# ═══════════════════════════════════════════════════════════


@user_router.message(F.video | F.document | F.audio | F.voice, F.chat.type == "private")
async def block_media(message: types.Message):
    """
    ✅ Admin panel ochiq bo'lsa — o'chirmaydi
    ✅ Admin bo'lsa ham o'chirmaydi
    ✅ Kanal videolariga tegmaydi
    """
    user_id = message.from_user.id
    if is_admin_panel_active(user_id):
        return
    if await _is_admin(user_id):
        return
    try:
        await message.delete()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  MATN XABARLAR
# ═══════════════════════════════════════════════════════════


@user_router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: types.Message):
    """
    ✅ Admin panel ochiq bo'lsa — o'chirmaydi
    ✅ Admin bo'lsa ham o'chirmaydi
    ✅ Inline link → 2-rasmdagi dizayn
    ✅ anime_ID format → 2-rasmdagi dizayn
    ✅ Oddiy user matn → o'chiriladi
    """
    text = message.text.strip()
    user_id = message.from_user.id

    if text.isdigit():
        return

    # Inline dan kelgan link → 2-rasmdagi dizayn
    if "?start=anime_" in text:
        try:
            anime_id_str = text.split("?start=anime_")[-1].strip()
            if anime_id_str.isdigit():
                try:
                    await message.delete()
                except Exception:
                    pass
                await _show_anime_card(message, int(anime_id_str), user_id, from_inline=True)
                return
        except Exception:
            pass

    # anime_123 format
    if text.startswith("anime_"):
        try:
            anime_id = int(text.replace("anime_", "").strip())
            try:
                await message.delete()
            except Exception:
                pass
            await _show_anime_card(message, anime_id, user_id, from_inline=True)
            return
        except ValueError:
            pass

    # Admin panel ochiq bo'lsa — o'chirmaydi
    if is_admin_panel_active(user_id):
        return

    # Admin bo'lsa ham o'chirmaydi
    if await _is_admin(user_id):
        return

    # Oddiy user — o'chirish
    try:
        await message.delete()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  MENING DIDIM
# ═══════════════════════════════════════════════════════════


@user_router.callback_query(F.data == "my_taste")
async def my_taste_profile(call: types.CallbackQuery):
    user_id = call.from_user.id

    try:
        from utils.recommendation import build_identity_label, get_or_create_taste_profile

        async with AsyncSessionLocal() as session:
            profile = await get_or_create_taste_profile(session, user_id)
        identity = build_identity_label(profile)
        genres = dict(profile.fav_genres or {})
        top_g = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:3]
        tags = dict(profile.fav_tags or {})
        top_t = sorted(tags.items(), key=lambda x: x[1], reverse=True)[:3]
        has_data = bool(top_g or top_t)
    except Exception:
        has_data = False
        identity = "🎌 Anime muxlisi"
        top_g = []
        top_t = []

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")]]
    )

    if not has_data:
        text = (
            "👤 <b>Sizning Did Profilingiz</b>\n\n"
            "📊 Hozircha ma'lumot to'planmagan.\n\n"
            "Ko'proq anime ko'ring — tizim avtomatik ravishda "
            "sevimli janrlar va kayfiyatingizni aniqlaydi! 🎌\n\n"
            "<i>Qanchalik ko'p kontent ko'rsangiz, tavsiyalar shunchalik aniq bo'ladi.</i>"
        )
    else:
        g_text = "\n".join(f"  • {g}: {c} marta" for g, c in top_g) or "  Hali ma'lumot yo'q"
        t_text = "\n".join(f"  • {t}: {c} marta" for t, c in top_t) or "  Hali ma'lumot yo'q"
        text = (
            f"👤 <b>Sizning Did Profilingiz</b>\n\n"
            f"🎯 <b>{identity}</b>\n\n"
            f"🎭 <b>Sevimli janrlar:</b>\n{g_text}\n\n"
            f"🏷 <b>Sevimli teglar:</b>\n{t_text}\n\n"
            "<i>Ko'rgan kontentlaringiz asosida yig'iladi.</i>"
        )

    try:
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await call.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()
