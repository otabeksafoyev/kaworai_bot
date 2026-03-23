import asyncio
import logging
import sys
import os

# Papka yo'lini Python'ga tanitish
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Kerakli narsalarni import qilish
from loader import bot, dp
from database.engine import init_db
from handlers.admin import admin_router
from handlers.callbacks import callback_router
# from handlers.users import user_router

async def main():
    # 1. Logging sozlamasini eng tepaga qo'yamiz (hamma narsani ko'rish uchun)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    # 2. Ma'lumotlar bazasini ishga tushirish (Jadvallarni yaratish)
    logging.info("Ma'lumotlar bazasi jadvallari tekshirilmoqda...")
    try:
        await init_db()
        logging.info("Baza jadvallari tayyor.")
    except Exception as e:
        logging.error(f"Bazani yaratishda xato: {e}")
        return # Baza ishlamasa botni yuritishdan foyda yo'q

    # 3. Routerlarni dispatcherga ulash
    dp.include_router(admin_router)
    dp.include_router(callback_router)
    # dp.include_router(user_router)

    logging.info("Bot updates'larni tozalab, ishga tushmoqda...")

    # 4. Webhookni tozalash va Pollingni boshlash
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.error("Bot to'xtatildi!")