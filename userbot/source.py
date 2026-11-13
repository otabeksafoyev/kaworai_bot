"""Manba bot bilan suhbat: kodni yuboradi, nom va qismlarni yig'adi.
Manba botning javob formati ma'lum bo'lmagani uchun umumiy ishlaydi:
  1) kodni yuboradi,  2) kelgan matn/videolarni yig'adi,
  3) agar videolar kelmasa va raqamli tugmalar bo'lsa — har birini bosib qismlarni oladi."""
from __future__ import annotations

import asyncio
import logging
import re

from .parsers import episode_no

logger = logging.getLogger("userbot")


def is_video(m) -> bool:
    if getattr(m, "video", None):
        return True
    doc = getattr(m, "document", None)
    return bool(doc and (doc.mime_type or "").startswith("video"))


async def _drain(conv, idle: float, sink: list) -> None:
    while True:
        try:
            m = await asyncio.wait_for(conv.get_response(), idle)
        except asyncio.TimeoutError:
            return
        sink.append(m)


async def fetch_from_source(client, source_bot: str, code: str, idle: float = 15.0):
    """(info_text, {qism_raqami: telethon_message}) qaytaradi."""
    got: list = []
    async with client.conversation(source_bot, timeout=120, total_timeout=1800, max_messages=1000) as conv:
        await conv.send_message(code)
        await _drain(conv, idle, got)

        # Videolar kelmagan bo'lsa — raqamli tugmalar orqali qismlarni so'raymiz
        if not any(is_video(m) for m in got):
            for bm in [m for m in got if getattr(m, "buttons", None)]:
                for row in bm.buttons:
                    for b in row:
                        if getattr(b, "data", None) and re.fullmatch(r"\D{0,3}\d{1,4}\D{0,3}", b.text or ""):
                            try:
                                await b.click()
                            except Exception:
                                logger.warning("tugma bosilmadi: %s", b.text)
                                continue
                            await _drain(conv, 8.0, got)

    info_parts, episodes, seq = [], {}, 0
    for m in got:
        if is_video(m):
            seq += 1
            n = episode_no(m.message) or seq
            episodes.setdefault(n, m)
            if m.message:
                info_parts.append(m.message)
        elif m.message:
            info_parts.append(m.message)
    return "\n".join(info_parts), dict(sorted(episodes.items()))
