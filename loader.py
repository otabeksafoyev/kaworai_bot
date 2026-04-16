import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from data import config


logging.basicConfig(level=logging.INFO)

# Redis ulanishi — FSM state'ni saqlaydi. Jarayon restart bo'lsa ham
# foydalanuvchilar o'z qadamlarini yo'qotmaydi.
storage = RedisStorage.from_url(config.REDIS_URL)

# Bot va Dispatcher
#
# Telegram API ba'zida sekin javob beradi (10+ soniya). Agar timeout
# bo'lmasa, bitta sekin so'rov butun coroutine'ni bloklab qo'yadi va
# 200k foydalanuvchi scale'ida task'lar to'planib ketadi. Shuning uchun
# `AiohttpSession(timeout=...)` bilan qattiq vaqt chegarasi qo'yamiz.
# 60 soniya — odatdagi uzun so'rovlar (masalan `getChatMember` sekin
# kanalda) uchun yetarli, lekin cheksiz kutishdan himoyalaydi.
session = AiohttpSession(timeout=60)

bot = Bot(
    token=config.BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=storage)

# BU YERDA 'db' YO'Q, chunki u database/engine.py da
