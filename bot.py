import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import config
from database.engine import init_db
from middlewares.subscription import SubscriptionMiddleware
from middlewares.throttling import ThrottlingMiddleware
from handlers import user_router, admin_router, callback_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = RedisStorage.from_url(config.REDIS_URL)
dp = Dispatcher(storage=storage)

dp.message.middleware(ThrottlingMiddleware())
dp.message.middleware(SubscriptionMiddleware())
dp.callback_query.middleware(SubscriptionMiddleware())

dp.include_router(user_router)
dp.include_router(admin_router)
dp.include_router(callback_router)

async def main():
    await init_db()
    logger.info("✅ Bot ishga tushdi | 200k+ tayyor")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())