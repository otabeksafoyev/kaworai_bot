import asyncio
import logging
import sys
import os

# Papka yo'lini Python'ga tanitish (Importlar xato bermasligi uchun)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from loader import bot, dp
from database.engine import init_db

# Handlerlarni (Routerlarni) import qilish
from handlers.admin import admin_router
from handlers.callbacks import callback_router
from handlers.users import user_router      # /start va asosiy UI
from handlers.inline import inline_router   # Anime qidiruvi

async def on_startup():
    """Bot ishga tushganda bazani va boshqa tizimlarni tayyorlash"""
    logging.info("Ma'lumotlar bazasi jadvallari tekshirilmoqda...")
    try:
        await init_db()
        logging.info("Baza jadvallari tayyor.")
    except Exception as e:
        logging.error(f"Bazani yaratishda jiddiy xato: {e}")
        # Baza ulanmasa botni yurgizishdan ma'no yo'q
        sys.exit(1)

async def main():
    # 1. Logging sozlamalari (Ma'lumotlarni terminalga chiroyli chiqarish)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # 2. Bazani ishga tushiramiz
    await on_startup()

    # 3. Routerlarni Dispatcherga ulash
    # DIQQAT: Admin router har doim birinchi bo'lishi kerak
    dp.include_router(admin_router)
    dp.include_router(user_router)
    dp.include_router(callback_router)
    dp.include_router(inline_router)

    # 4. Bot haqida ma'lumot olish
    bot_info = await bot.get_me()
    print(f"--- BOT ISHGA TUSHDI ---\nUSER: @{bot_info.username}\nID: {bot_info.id}\n------------------------")

    # 5. Eskirib qolgan (bot o'chiqligida kelgan) xabarlarni o'chirib yuborish
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 6. Pollingni boshlash (Xabarlarni eshitish)
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Polling davomida xatolik: {e}")
    finally:
        # Bot to'xtaganda ulanishlarni xavfsiz yopish
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot foydalanuvchi tomonidan to'xtatildi.")