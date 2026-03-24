from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

# 1. AVVAL ROUTERNI ANIQLAYMIZ (Bu eng muhimi!)
user_router = Router()

def get_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    # 1-qator: Janr va Qidiruv
    builder.row(
        InlineKeyboardButton(text="✨ Janr bo'yicha qidirish", callback_data="genres"),
        InlineKeyboardButton(text="🔎 Qidiruv", switch_inline_query_current_chat="")
    )
    # 2-qator: Obunalarim va Kawaii Pass
    builder.row(
        InlineKeyboardButton(text="❤️ Obunalarim", callback_data="my_subs"),
        InlineKeyboardButton(text="🟢 Kawaii Pass", callback_data="kawaii_pass")
    )
    return builder.as_markup()

# 2. ENDI ESA UNDAN FOYDALANAMIZ
@user_router.message(CommandStart())
async def cmd_start(message: types.Message):
    caption = (
        "<b>Kawaii — Anime dunyosiga xush kelibsiz!</b>\n\n"
        "⚠️ <b>DIQQAT! BOT YANGILANISH HOLATIDA...</b>\n"
        "Botda texnik ishlar olib borilmoqda, ba'zi funksiyalar vaqtinchalik ishlamasligi mumkin.\n\n"
        "• 8 ta foydalanuvchi anime tomosha qilmoqda\n"
        "• Eng ko'p tomosha qilinayotgan anime - <b>Naruto: Bo'ron yilnomalari</b>"
    )
    
    # Ishlaydigan rasm linki (Bad Request xatosi bermasligi uchun)
    photo_url = "https://i.postimg.cc/hj8Lrw0j/Screenshot-2026-03-24-014815.jpg" 
    
    try:
        await message.answer_photo(
            photo=photo_url,
            caption=caption,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        # Agar rasm yuklanmasa, matnni o'zini yuboradi
        await message.answer(
            text=caption,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )

# Boshqa xabarlarga javob bermaslik uchun (Promptdagi talab)
@user_router.message()
async def ignore_all_messages(message: types.Message):
    return