from aiogram import Router, F, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from sqlalchemy import select

# Proyektdagi importlar
from database.models import User, Anime, SubscriptionChannel
from database.engine import AsyncSessionLocal

user_router = Router()

# --- YORDAMCHI FUNKSIYALAR ---

def get_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✨ Janr bo'yicha qidirish", callback_data="genres"),
        InlineKeyboardButton(text="🔎 Qidiruv", switch_inline_query_current_chat="")
    )
    builder.row(
        InlineKeyboardButton(text="❤️ Obunalarim", callback_data="my_subs"),
        InlineKeyboardButton(text="🟢 Kawaii Pass", callback_data="kawaii_pass")
    )
    return builder.as_markup()

async def check_subscription(bot, user_id, session):
    """Majburiy obunani tekshirish"""
    channels = await session.scalars(select(SubscriptionChannel))
    not_subbed = []
    
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch.channel_id, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                not_subbed.append(ch)
        except Exception:
            continue # Agar bot kanalda admin bo'lmasa yoki xato bersa o'tkazib yuboradi
    return not_subbed

# --- ASOSIY HANDLERLAR ---

@user_router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    async with AsyncSessionLocal() as session:
        # 1. Foydalanuvchini bazaga qo'shish (agar yo'q bo'lsa)
        user = await session.get(User, user_id)
        if not user:
            new_user = User(telegram_id=user_id, full_name=message.from_user.full_name)
            session.add(new_user)
            await session.commit()

        # 2. Majburiy obunani tekshirish
        not_subbed = await check_subscription(message.bot, user_id, session)
        if not_subbed:
            kb = InlineKeyboardBuilder()
            for ch in not_subbed:
                kb.row(InlineKeyboardButton(text=f"➕ {ch.username}", url=f"https://t.me/{ch.username.replace('@', '')}"))
            kb.row(InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subs"))
            return await message.answer("<b>Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:</b>", 
                                        reply_markup=kb.as_markup(), parse_mode="HTML")

        # 3. Deep-linking (Kanaldan anime ko'rish uchun kelgan bo'lsa)
        args = command.args
        if args and args.startswith("anime_"):
            anime_id = int(args.replace("anime_", ""))
            anime = await session.get(Anime, anime_id)
            if anime:
                # Animeni to'g'ridan-to'g'ri chiqarish
                caption = (
                    f"🎬 <b>{anime.title}</b>\n\n"
                    f"📅 Yili: {anime.year}\n"
                    f"🎭 Janri: {', '.join(anime.genres) if anime.genres else 'Nomalum'}\n\n"
                    f"📖 <b>Tavsif:</b> {anime.description}"
                )
                return await message.answer_photo(
                    photo=anime.poster_file_id,
                    caption=caption,
                    reply_markup=InlineKeyboardBuilder().row(
                        InlineKeyboardButton(text="▶️ Tomosha qilish", callback_data=f"watch_{anime.id}")
                    ).as_markup(),
                    parse_mode="HTML"
                )

        # 4. Standart Start menyusi (Kawaii dizayn)
        caption = (
            "• 8 ta foydalanuvchi anime tomosha qilmoqda\n"
            "• Eng ko'p tomosha qilinayotgan anime - <b>Naruto: Bo'ron yilnomalari</b>"
        )
        photo_url = "https://i.postimg.cc/hj8Lrw0j/Screenshot-2026-03-24-014815.jpg"
        
        try:
            await message.answer_photo(
                photo=photo_url,
                caption=caption,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
        except Exception:
            await message.answer(text=caption, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")

# Barcha keraksiz xabarlarni e'tiborsiz qoldirish
@user_router.message()
async def ignore_all_messages(message: types.Message):
    return