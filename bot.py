import asyncio
import logging
import sys
import os

# Papka yo'lini tanitish
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from loader import bot
from handlers.admin import admin_router
# Agar handlers/users.py bo'lsa:
# from handlers.users import user_router 

async def main():
    # Routerlarni ulash
    dp.include_router(admin_router)
    # dp.include_router(user_router)

    logging.info("Bot ishga tushmoqda...")

    # Botni yangilashlarni tozalab ishga tushirish
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.error("Bot to'xtatildi!")