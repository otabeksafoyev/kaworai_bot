# main.py — agar albatta shu nom bilan ishlatmoqchi bo'lsangiz
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

# o'zingizning modullaringiz
from config import config
from database.engine import init_db
from middlewares import SubscriptionMiddleware, ThrottlingMiddleware
from handlers import user_router, admin_router, callback_router

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=RedisStorage.from_url(config.REDIS_URL))

dp.message.middleware(ThrottlingMiddleware())
dp.message.middleware(SubscriptionMiddleware())
dp.callback_query.middleware(SubscriptionMiddleware())

dp.include_routers(user_router, admin_router, callback_router)

async def main():
    await init_db()
    logging.info("Bot ishga tushdi")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())