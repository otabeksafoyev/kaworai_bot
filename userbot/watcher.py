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
        await rt.queue.put((event.message, cfg))

    rt.handler = on_post
    rt.client.add_event_handler(on_post, events.NewMessage(chats=[cfg["channel"]], incoming=True))
    logger.info("Kuzatuv: %s", cfg)


async def worker() -> None:
    while True:
        msg, cfg = await rt.queue.get()
        try:
            await process_post(rt.client, msg, cfg)
        except Exception:
            logger.exception("process_post xato")
            await rt.notify("✕ Ichki xato yuz berdi (loglarga qarang).")
