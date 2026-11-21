"""Jarayon ichidagi umumiy holat (login bot, Telethon klient va Kaworai Bot bir joyda)."""
from __future__ import annotations

import asyncio
import html
import logging
import time
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
    started_at: float = 0.0
    last_seen: dict = field(default_factory=dict)   # kanal id -> oxirgi post kelgan vaqt (time.time)
    current: str | None = None                      # hozir qayta ishlanayotgan post
    current_since: float = 0.0
    stage: str | None = None                        # joriy post qaysi bosqichda (/status va loglar uchun)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    confirms: dict = field(default_factory=dict)
    text_waiter: asyncio.Future | None = None

    def progress(self) -> "Progress":
        return Progress(self)

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


class Progress:
    """Bitta postning jonli hisoboti: bitta xabar tahrirlanib boradi, shunda qaysi bosqichda ekani ko'rinib turadi
    (qotib qolsa ham oxirgi qator qayerda to'xtaganini ko'rsatadi). Har bir qator logga ham yoziladi."""
    MIN_GAP = 1.2          # Telegram tahrirlash chegarasiga tushmaslik uchun

    def __init__(self, rt: "Runtime"):
        self.rt, self.title, self.lines = rt, "", []
        self.msg_id: int | None = None
        self._last = 0.0
        self._dirty = False

    async def begin(self, title: str, header: str) -> None:
        self.title = title
        self.lines = [header]
        await self._push(force=True)

    async def step(self, text: str, replace: bool = False) -> None:
        if replace and len(self.lines) > 1 and self.lines[-1].startswith("◌"):   # faqat "jarayonda" qatorni almashtiramiz, ✓ qoladi
            self.lines[-1] = text
        else:
            self.lines.append(text)
        self.rt.stage = text
        logger.info("[%s] %s", self.title or "post", text)
        self._dirty = True
        await self._push()

    async def flush(self) -> None:
        if self._dirty:
            await self._push(force=True)

    async def _push(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last < self.MIN_GAP:
            return
        self._last, self._dirty = now, False
        body = f"◈ <b>{html.escape(self.title)}</b>\n" + "\n".join(html.escape(x) for x in self.lines[-14:])
        try:
            if self.msg_id is None:
                m = await self.rt.login_bot.send_message(self.rt.admin_id, body, parse_mode="HTML")
                self.msg_id = m.message_id
            else:
                await self.rt.login_bot.edit_message_text(body, chat_id=self.rt.admin_id, message_id=self.msg_id, parse_mode="HTML")
        except Exception as e:                       # "message is not modified" va tarmoq xatolari hisobotni to'xtatmasin
            if "not modified" not in str(e):
                logger.warning("progress xabari yuborilmadi: %s", e)


rt = Runtime()
