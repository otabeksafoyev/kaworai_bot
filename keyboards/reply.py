from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def admin_reply_keyboard():
    kb = [
        [KeyboardButton(text="➕ Anime qo‘shish"), KeyboardButton(text="📝 Anime tahrirlash")],
        [KeyboardButton(text="🗑 Anime o‘chirish"), KeyboardButton(text="📊 Statistika")],
        [KeyboardButton(text="📤 Export JSON"), KeyboardButton(text="📥 Hamkor qo‘shish")],
        [KeyboardButton(text="📡 Kanal qo‘shish"), KeyboardButton(text="📰 News kanali")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)