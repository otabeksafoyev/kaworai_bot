import asyncio
from aiogram import Router, F, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from database.models import Anime, Series, User, AnimeSubscription
from database.engine import AsyncSessionLocal
from database.queries import get_or_create_user, get_active_channels, is_subscribed_anime
from middlewares.subscription import check_subscription, get_sub_keyboard
from datetime import datetime

user_router = Router()

PHOTO_URL = "https://i.postimg.cc/zDpjp9Mz/kawaro-(1)-(3).jpg"


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✨ Janr bo'yicha", callback_data="genres"),
            InlineKeyboardButton(text="🔎 Qidiruv", switch_inline_query_current_chat=""),
        ],
        [
            InlineKeyboardButton(text="🔢 Kod orqali qidirish", callback_data="search_by_code"),
            InlineKeyboardButton(text="❤️ Obunalarim", callback_data="my_subs"),
        ],
        [
            InlineKeyboardButton(text="🟢 Kaworai Pro", callback_data="kawaii_pass"),
        ],
    ])


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
            photo=PHOTO_URL,
            caption=caption,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        await msg.answer(
            caption,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )


# ═══════════════════════════════════════════════════════════
#  /start
# ═══════════════════════════════════════════════════════════

@user_router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        await get_or_create_user(
            session=session,
            telegram_id=user_id,
            full_name=message.from_user.full_name,
            username=message.from_user.username,
        )
        channels = await get_active_channels(session)

    not_subbed = await check_subscription(message.bot, user_id, channels)
    if not_subbed:
        kb = get_sub_keyboard(not_subbed)
        return await message.answer(
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
            + "\n".join(f"• {ch.channel_name}" for ch in not_subbed),
            reply_markup=kb,
            parse_mode="HTML"
        )

    args = command.args or ""

    anime_id = None
    if args.startswith("anime_"):
        try:
            anime_id = int(args.replace("anime_", ""))
        except ValueError:
            pass
    elif args.startswith("kod_"):
        try:
            anime_id = int(args.replace("kod_", ""))
        except ValueError:
            pass
    elif args.isdigit():
        anime_id = int(args)

    if anime_id:
        try:
            await message.delete()
        except Exception:
            pass
        await _show_anime_card(message, anime_id, user_id)
        return

    await send_main_menu(message)


# ═══════════════════════════════════════════════════════════
#  ANIME KARTOCHKA
# ═══════════════════════════════════════════════════════════

async def _show_anime_card(message: types.Message, anime_id: int, user_id: int):
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

        user   = await session.get(User, user_id)
        now    = datetime.utcnow()
        is_pro = bool(
            user and user.is_pro and
            (not user.pro_until or user.pro_until > now)
        )

        ep_res = await session.execute(
            select(Series)
            .where(Series.anime_id == anime_id)
            .order_by(Series.episode.asc())
            .limit(1)
        )
        first_ep   = ep_res.scalar_one_or_none()
        subscribed = await is_subscribed_anime(session, anime_id, user_id)

    genres_text = ", ".join(anime.genres or []) or "Nomalum"
    tags_text   = ", ".join((anime.tags or [])[:3])
    lock_str    = " 🔒 Pro" if anime.is_pro_locked else ""
    sub_icon    = "🔔" if subscribed else "🔕"
    sub_txt     = "Obunani bekor qilish" if subscribed else "🔔 Obuna bo'lish"

    type_emoji = {"anime": "🎌", "movie": "🎥", "serial": "📺", "dorama": "🌸"}
    emoji      = type_emoji.get(anime.content_type or "anime", "🎬")

    caption = (
        f"{emoji} <b>{anime.title}</b>"
        + (f" ({anime.year})" if anime.year else "")
        + lock_str + "\n\n"
        f"🎭 {genres_text}\n"
        + (f"🏷 {tags_text}\n" if tags_text else "")
        + f"⭐ {anime.rating:.1f} ({anime.rating_count} ovoz)\n"
        f"🆔 Kod: <code>{anime.id}</code>\n\n"
        f"📖 {(anime.description or '')[:300]}"
    )

    kb_rows = []

    if anime.is_pro_locked and not is_pro:
        kb_rows.append([InlineKeyboardButton(
            text="🔒 Faqat Kaworai Pro uchun",
            callback_data="kawaii_pass"
        )])
    elif first_ep:
        kb_rows.append([InlineKeyboardButton(
            text="▶️ 1-qismdan tomosha qilish",
            callback_data=f"watch_start_{anime_id}"
        )])
    else:
        kb_rows.append([InlineKeyboardButton(
            text="⏳ Qismlar hali qo'shilmagan",
            callback_data="no_episodes"
        )])

    kb_rows.append([
        InlineKeyboardButton(text=f"{sub_icon} {sub_txt}", callback_data=f"toggle_sub_{anime_id}")
    ])
    kb_rows.append([
        InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    try:
        if anime.poster_file_id:
            await message.answer_photo(
                photo=anime.poster_file_id,
                caption=caption,
                reply_markup=kb,
                parse_mode="HTML"
            )
        elif anime.inline_thumbnail_url:
            await message.answer_photo(
                photo=anime.inline_thumbnail_url,
                caption=caption,
                reply_markup=kb,
                parse_mode="HTML"
            )
        else:
            await message.answer(caption, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await message.answer(caption, reply_markup=kb, parse_mode="HTML")


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
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")
    ]])
    try:
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await call.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


@user_router.message(F.text.regexp(r'^\d+$'))
async def handle_code_input(message: types.Message):
    user_id  = message.from_user.id
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

    await _show_anime_card(message, anime_id, user_id)


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
            rows.append([InlineKeyboardButton(
                text=f"🎬 {lock}{anime.title}",
                callback_data=f"anime_info_{anime.id}"
            )])
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
                reply_markup=kb, parse_mode="HTML"
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

@user_router.message(F.video | F.document | F.audio | F.voice)
async def block_media(message: types.Message):
    try:
        await message.delete()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  MATN XABARLAR
# ═══════════════════════════════════════════════════════════

@user_router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: types.Message):
    text = message.text.strip()

    # Raqam — handle_code_input boshqaradi
    if text.isdigit():
        return

    # ✅ Inline dan kelgan "anime_123" formatini ushlash
    if text.startswith("anime_"):
        try:
            anime_id = int(text.replace("anime_", ""))
            try:
                await message.delete()
            except Exception:
                pass
            await _show_anime_card(message, anime_id, message.from_user.id)
            return
        except ValueError:
            pass

    # Boshqa barcha matnlarni o'chirish
    try:
        await message.delete()
    except Exception:
        pass