import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from data import config
from handlers import admin_router, user_router # xatolik bergan joy

async def main():
    logging.basicConfig(level=logging.INFO)

    # Redis ulanishi (Tezkorlik uchun)
    storage = RedisStorage.from_url(config.REDIS_URL)

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=storage)

    # Routerlarni ulash
    dp.include_routers(
        admin_router,
        user_router
    )

    # Bazani ishga tushirish (PostgreSQL)
    # Bu yerda db.create() funksiyasini chaqirishingiz kerak

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.error("Bot to'xtatildi!")