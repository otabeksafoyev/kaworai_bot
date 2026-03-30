import asyncio
import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from loader import bot, dp
from database.engine import init_db
from middlewares.subscription import SubscriptionMiddleware

from handlers.admin import admin_router
from handlers.callbacks import callback_router
from handlers.users import user_router
from handlers.inline import inline_router
from handlers.genres import genre_router
from handlers.admin_pro import pro_admin_router
from handlers.users_pro import pro_user_rout





async def on_startup():
    logging.info("Ma'lumotlar bazasi jadvallari tekshirilmoqda...")
    try:
        await init_db()
        logging.info("Baza jadvallari tayyor.")
    except Exception as e:
        logging.error(f"Bazani yaratishda jiddiy xato: {e}")
        sys.exit(1)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("bot.log", encoding="utf-8"),  # Loglarni faylga ham yozish
        ]
    )

    await on_startup()

    # Routerlar (admin har doim birinchi!)
    dp.include_router(admin_router)
    dp.include_router(user_router)
    dp.include_router(callback_router)
    dp.include_router(inline_router)
    dp.include_router(pro_admin_router)
    dp.include_router(pro_user_router)


    
    # Obuna tekshiruv middleware
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())
    dp.include_router(genre_router)
    bot_info = await bot.get_me()
    print(f"--- BOT ISHGA TUSHDI ---\nUSER: @{bot_info.username}\nID: {bot_info.id}\n------------------------")

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Polling davomida xatolik: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot foydalanuvchi tomonidan to'xtatildi.")