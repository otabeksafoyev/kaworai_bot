"""Kanalni kuzatish: yangi post kelsa navbatga qo'yadi, bitta-bittadan qayta ishlaydi."""
from __future__ import annotations

import asyncio
import logging

from telethon import events

from . import storage
from .pipeline import process_post
from .runtime import rt

logger = logging.getLogger("userbot")


async def start_watcher() -> None:
    cfg = await storage.load_watch()
    if not (rt.client and cfg):
        return
    if rt.handler:
        rt.client.remove_event_handler(rt.handler)

    async def on_post(event):
        m = event.message
        logger.info("Post keldi: chat=%s id=%s out=%s matn=%r", m.chat_id, m.id, m.out, (m.message or "")[:80])
        await rt.queue.put((m, cfg))

    rt.handler = on_post
    rt.client.add_event_handler(on_post, events.NewMessage(chats=[cfg["channel"]]))
    logger.info("Kuzatuv: %s", cfg)
    try:
        ent = await rt.client.get_entity(cfg["channel"])
        logger.info("Kuzatuv kanali: %s (id=%s)", getattr(ent, "title", ent), cfg["channel"])
    except Exception as e:
        logger.error("Kuzatuv kanali topilmadi (akkaunt a'zo emasmi?): %s: %s", type(e).__name__, e)
        await rt.notify(f"✕ Kuzatuv kanali ({cfg['channel']}) topilmadi — akkaunt kanalga a'zo ekanini tekshiring ({type(e).__name__}).")


async def worker() -> None:
    while True:
        msg, cfg = await rt.queue.get()
        try:
            await process_post(rt.client, msg, cfg)
        except Exception:
            logger.exception("process_post xato")
            await rt.notify("✕ Ichki xato yuz berdi (loglarga qarang).")
