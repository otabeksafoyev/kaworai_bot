import asyncio
from aiogram import Router, F, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import Anime, Series
from database.engine import AsyncSessionLocal
from database.queries import get_or_create_user, get_active_channels
from middlewares.subscription import check_subscription, get_sub_keyboard
from sqlalchemy import select

user_router = Router()

PHOTO_URL = "https://i.postimg.cc/zDpjp9Mz/kawaro-(1)-(3).jpg"


def get_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✨ Janr bo'yicha qidirish", callback_data="genres"),
        InlineKeyboardButton(text="🔎 Qidiruv", switch_inline_query_current_chat="")
    )
    builder.row(
        InlineKeyboardButton(text="❤️ Obunalarim", callback_data="my_subs"),
        InlineKeyboardButton(text="🟢 Kaworai Pro", callback_data="kawaii_pass")
    )
    return builder.as_markup()


async def send_main_menu(message: types.Message):
    caption = "🎌 <b>Kaworai Anime Botga xush kelibsiz!</b>\n\n"
    try:
        await message.answer_photo(
            photo=PHOTO_URL,
            caption=caption,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        await message.answer(
            text=caption,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )


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

    # ✅ Deep-link: ?start=anime_ID — poster + 1-qism tugmasi chiqadi
    args = command.args or ""
    if args.startswith("anime_"):
        try:
            anime_id = int(args.replace("anime_", ""))
        except ValueError:
            anime_id = None

        if anime_id:
            async with AsyncSessionLocal() as session:
                anime = await session.get(Anime, anime_id)
                first_ep = None
                ep_count = 0
                if anime:
                    ep_result = await session.execute(
                        select(Series)
                        .where(Series.anime_id == anime_id)
                        .order_by(Series.episode.asc())
                        .limit(1)
                    )
                    first_ep = ep_result.scalar_one_or_none()
                    from sqlalchemy import func
                    ep_count_result = await session.execute(
                        select(func.count(Series.id)).where(Series.anime_id == anime_id)
                    )
                    ep_count = ep_count_result.scalar() or 0

            if anime:
                genres_text = ', '.join(anime.genres) if anime.genres else 'Nomalum'
                total_ep_text = str(anime.total_episodes) if anime.total_episodes else "?"

                caption = (
                    f"🎬 <b>{anime.title}</b>\n\n"
                    f"📅 Yili: {anime.year}\n"
                    f"🎭 Janri: {genres_text}\n"
                    f"⭐ Reyting: {anime.rating} ({anime.rating_count} ovoz)\n"
                    f"📺 Qismlar: {ep_count}/{total_ep_text}\n\n"
                    f"📖 <b>Tavsif:</b> {anime.description}"
                )

                kb = InlineKeyboardBuilder()
                if first_ep:
                    # ✅ 1-qismni darhol ko'rsatish
                    kb.row(InlineKeyboardButton(
                        text="▶️ 1-qismni ko'rish",
                        callback_data=f"watch_{anime.id}"
                    ))
                else:
                    kb.row(InlineKeyboardButton(
                        text="⏳ Qismlar hali qo'shilmagan",
                        callback_data="no_episodes"
                    ))
                kb.row(InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu"))

                # ✅ Posterda total_episodes ko'rinadi
                return await message.answer_photo(
                    photo=anime.poster_file_id,
                    caption=caption,
                    reply_markup=kb.as_markup(),
                    parse_mode="HTML"
                )

    await send_main_menu(message)


# ✅ Obunani tekshirish

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
                parse_mode="HTML"
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
    await call.answer("Bekor qilindi.", show_alert=False)


@user_router.callback_query(F.data == "kawaii_pass")
async def kawaii_pass_cb(call: types.CallbackQuery):
    await call.answer("🟢 Kaworai Pro tez kunda ishga tushadi!", show_alert=True)


@user_router.callback_query(F.data == "no_episodes")
async def no_episodes(call: types.CallbackQuery):
    await call.answer("⏳ Qismlar hali qo'shilmagan!", show_alert=True)


# ✅ Noma'lum xabarlar — 3 soniyadan keyin o'chadi
@user_router.message()
async def unknown_message(message: types.Message):
    sent = await message.answer("❗ <b>/start</b> buyrug'ini yozing", parse_mode="HTML")
    await asyncio.sleep(3)
    try:
        await sent.delete()
        await message.delete()
    except Exception:
        pass