"""Ishga tushirish:  python -m userbot.main   (kaworai_bot papkasidan)"""
from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from telethon import TelegramClient
from telethon.sessions import StringSession

from data import config

from . import storage
from .login_bot import router
from .targets_bot import router as targets_router
from .runtime import rt
from .watcher import start_watcher, worker


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    rt.admin_id = config.ADMIN_ID
    rt.kaworai_bot = Bot(config.BOT_TOKEN)
    rt.login_bot = Bot(os.environ["USERBOT_LOGIN_BOT_TOKEN"])

    saved = await storage.load_login()
    if saved:
        api_id, api_hash, sess = saved
        rt.client = TelegramClient(StringSession(sess), api_id, api_hash)
        await rt.client.connect()
        if await rt.client.is_user_authorized():
            await rt.client.get_dialogs()   # kanal/maxfiy kanal entity keshi uchun
            await start_watcher()
        else:
            rt.client = None
            await storage.clear_login()

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(targets_router)   # login_bot dagi umumiy matn handlerdan OLDIN bo'lishi shart
    dp.include_router(router)
    asyncio.create_task(worker())
    await dp.start_polling(rt.login_bot)


if __name__ == "__main__":
    asyncio.run(main())
