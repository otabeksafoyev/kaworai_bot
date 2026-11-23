"""Ishga tushirish:  python -m userbot.main   (kaworai_bot papkasidan)"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from telethon import TelegramClient
from telethon.sessions import StringSession

from data import config

from . import storage
from .login_bot import router, setup_menu
from .targets_bot import router as targets_router
from .runtime import rt
from .watcher import describe_watches, health_loop, start_watcher, worker


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    rt.started_at = time.time()
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
            try:
                from . import folders
                await folders.refresh_all(rt.client)       # papkaga yangi kanal qo'shilgan bo'lishi mumkin
            except Exception:
                logging.getLogger("userbot").warning("papkalar yangilanmadi", exc_info=True)
            await start_watcher()
            asyncio.create_task(health_loop())
            fl = await storage.load_folders()
            await rt.notify("✓ Userbot ishga tushdi.\n⌕ Kuzatuv kanallari:\n" + describe_watches(await storage.load_watches())
                            + (f"\n📁 Papkalar: {len(fl)} (jami {sum(len(f['channels']) for f in fl)} kanal)" if fl else ""))
        else:
            rt.client = None
            await storage.clear_login()
            await rt.notify("✕ Saqlangan Telegram sessiyasi yaroqsiz (bekor qilingan) — userbot postlarni ko'rmaydi.\n"
                            "Ko'pincha bir sessiya ikki joyda bir vaqtda ishlaganidan bo'ladi. /start orqali qayta ulang.")

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(targets_router)   # login_bot dagi umumiy matn handlerdan OLDIN bo'lishi shart
    dp.include_router(router)
    await setup_menu(rt.login_bot)
    asyncio.create_task(worker())
    await dp.start_polling(rt.login_bot)


if __name__ == "__main__":
    asyncio.run(main())
