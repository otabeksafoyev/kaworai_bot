import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from data import config

logging.basicConfig(level=logging.INFO)

# Redis ulanishi
storage = RedisStorage.from_url(config.REDIS_URL)

# Bot va Dispatcher
bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=storage)

# BU YERDA 'db' YO'Q, chunki u database/engine.py da