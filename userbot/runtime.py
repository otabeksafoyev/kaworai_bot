"""Jarayon ichidagi umumiy holat (login bot, Telethon klient va Kaworai Bot bir joyda)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("userbot")


@dataclass
class Runtime:
    admin_id: int = 0
    kaworai_bot: Bot | None = None      # asosiy bot (faqat API chaqiruvlari: poster file_id)
    login_bot: Bot | None = None        # userbotni boshqaradigan bot
    client: object = None               # Telethon TelegramClient
    handler: object = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    confirms: dict = field(default_factory=dict)
    text_waiter: asyncio.Future | None = None

    async def notify(self, text: str) -> None:
        try:
            await self.login_bot.send_message(self.admin_id, text, parse_mode="HTML")
        except Exception:
            logger.warning("notify xato", exc_info=True)

    async def ask_text(self, prompt: str, timeout: int = 900) -> str | None:
        """Adminga savol beradi, uning keyingi matnli javobini kutadi."""
        loop = asyncio.get_running_loop()
        self.text_waiter = loop.create_future()
        await self.notify(prompt)
        try:
            return await asyncio.wait_for(self.text_waiter, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.text_waiter = None

    async def confirm(self, text: str, poster: bytes | None, timeout: int = 1800) -> str:
        """'ok' | 'retry' | 'cancel' qaytaradi."""
        job = uuid.uuid4().hex[:8]
        fut = asyncio.get_running_loop().create_future()
        self.confirms[job] = fut
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✓ Ha, qo'shish", callback_data=f"ub_ok:{job}")],
            [InlineKeyboardButton(text="↻ Boshqa nom bilan", callback_data=f"ub_retry:{job}"),
             InlineKeyboardButton(text="✕ Bekor", callback_data=f"ub_cancel:{job}")],
        ])
        try:
            if poster:
                await self.login_bot.send_photo(self.admin_id, BufferedInputFile(poster, "poster.jpg"))
            await self.login_bot.send_message(self.admin_id, text, parse_mode="HTML", reply_markup=kb)
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return "cancel"
        finally:
            self.confirms.pop(job, None)


rt = Runtime()
