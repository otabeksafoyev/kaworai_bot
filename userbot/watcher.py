"""Kanallarni kuzatish: yangi post kelsa navbatga qo'yadi, bitta-bittadan qayta ishlaydi."""
from __future__ import annotations

import asyncio
import logging

from telethon import events

from . import storage
from .pipeline import process_post
from .runtime import rt

logger = logging.getLogger("userbot")


def _make_handler(cfg: dict):
    async def on_post(event):
        m = event.message
        logger.info("Post keldi: chat=%s id=%s out=%s matn=%r", m.chat_id, m.id, m.out, (m.message or "")[:80])
        await rt.queue.put((m, cfg))
    return on_post


async def start_watcher() -> None:
    """Barcha kuzatuv kanallarini (qayta) ro'yxatdan o'tkazadi."""
    for h in (rt.handler or []):
        try:
            rt.client.remove_event_handler(h)
        except Exception:
            pass
    rt.handler = []
    items = await storage.load_watches()
    if not (rt.client and items):
        return
    for cfg in items:
        h = _make_handler(cfg)
        rt.client.add_event_handler(h, events.NewMessage(chats=[cfg["channel"]]))
        rt.handler.append(h)
        logger.info("Kuzatuv: %s", cfg)
        try:
            ent = await rt.client.get_entity(cfg["channel"])
            logger.info("Kuzatuv kanali: %s (id=%s)", getattr(ent, "title", ent), cfg["channel"])
        except Exception as e:
            logger.error("Kuzatuv kanali topilmadi (akkaunt a'zo emasmi?): %s: %s", type(e).__name__, e)
            await rt.notify(f"✕ Kuzatuv kanali ({cfg.get('title') or cfg['channel']}) topilmadi — akkaunt kanalga a'zo ekanini tekshiring ({type(e).__name__}).")


async def worker() -> None:
    while True:
        msg, cfg, *rest = await rt.queue.get()
        try:
            await process_post(rt.client, msg, cfg, rest[0] if rest else 0)
        except Exception:
            logger.exception("process_post xato")
            await rt.notify("✕ Ichki xato yuz berdi (loglarga qarang).")
