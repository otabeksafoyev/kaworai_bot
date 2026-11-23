"""Kanallarni kuzatish: yangi post kelsa navbatga qo'yadi, bitta-bittadan qayta ishlaydi."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from telethon import events, utils
from telethon.tl import types as T

from . import folders, storage
from .pipeline import process_post
from .runtime import rt

logger = logging.getLogger("userbot")

POST_TIMEOUT = int(os.environ.get("UB_POST_TIMEOUT", "1500"))        # bitta post eng ko'pi bilan necha soniya (qotib qolmasligi uchun)
FOLDER_REFRESH = int(os.environ.get("UB_FOLDER_REFRESH", str(6 * 3600)))    # papkalarni necha soniyada qayta o'qiydi
HEALTH_INTERVAL = int(os.environ.get("UB_HEALTH_INTERVAL", "120"))   # sessiya holatini necha soniyada tekshiradi


def describe_watches(items: list[dict]) -> str:
    return "\n".join(f"• {w.get('title') or w['channel']} — {w['source_bot']} • {w['content_type']}" for w in items) or "—"


def _make_handler(cfg: dict):
    async def on_post(event):
        m = event.message
        logger.info("Post keldi: chat=%s id=%s out=%s matn=%r", m.chat_id, m.id, m.out, (m.message or "")[:80])
        rt.last_seen[cfg["channel"]] = time.time()
        await rt.queue.put((m, cfg))
    return on_post


def _register_folders(fl: list[dict], skip: set[int]) -> None:
    """Papka kanallari: bitta umumiy handler ("yangi qism" rejimi)."""
    fmap = {utils.get_peer_id(T.PeerChannel(cid)): cfg for cid, cfg in folders.watch_map(fl, skip).items()}
    if not fmap:
        return

    async def on_folder_post(event):
        m = event.message
        cfg = fmap.get(m.chat_id)
        if cfg is None or not (m.message or "").strip():
            return
        logger.info("Papka posti: %s id=%s matn=%r", cfg["title"], m.id, (m.message or "")[:60])
        rt.last_seen[cfg["channel"]] = time.time()
        await rt.queue.put((m, cfg))

    rt.client.add_event_handler(on_folder_post, events.NewMessage(chats=list(fmap)))   # fmap kalitlari -100... (to'liq) ID
    rt.handler.append(on_folder_post)
    logger.info("Papka kanallari kuzatuvda: %s ta", len(fmap))


async def start_watcher() -> None:
    """Barcha kuzatuv kanallarini (qayta) ro'yxatdan o'tkazadi."""
    for h in (rt.handler or []):
        try:
            rt.client.remove_event_handler(h)
        except Exception:
            pass
    rt.handler = []
    items = await storage.load_watches()
    fl = await storage.load_folders()
    if not rt.client:
        return
    try:
        _register_folders(fl, {w["channel"] for w in items})
    except Exception:                                  # papka xatosi asosiy kuzatuvni to'xtatmasin
        logger.exception("papka kanallari ro'yxatdan o'tmadi")
        await rt.notify("! Papka kanallari ulanmadi (loglarga qarang) — oddiy kuzatuv davom etadi.")
    if not items:
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
        rt.current, rt.current_since = f"{cfg.get('title') or cfg['channel']} / post {msg.id}", time.time()
        try:
            await asyncio.wait_for(process_post(rt.client, msg, cfg, rest[0] if rest else 0), POST_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error("post %s %ss ichida tugamadi — to'xtatildi", msg.id, POST_TIMEOUT)
            await rt.notify(f"✕ Post ({msg.id}) {POST_TIMEOUT // 60} daqiqada tugamadi — to'xtatildi, keyingisiga o'tdim.")
        except Exception:
            logger.exception("process_post xato")
            await rt.notify("✕ Ichki xato yuz berdi (loglarga qarang).")
        finally:
            rt.current = None


async def health_loop() -> None:
    """Telegram sessiyasi yaroqliligini tekshiradi; bekor qilingan bo'lsa (masalan bir sessiya ikki joyda ishlasa) adminga aytadi."""
    was_ok = True
    last_refresh = time.time()
    while True:
        await asyncio.sleep(HEALTH_INTERVAL)
        if rt.client is not None and time.time() - last_refresh > FOLDER_REFRESH:
            last_refresh = time.time()
            try:
                if await folders.refresh_all(rt.client):
                    logger.info("papka kanallari o'zgardi — kuzatuv yangilanyapti")
                    await start_watcher()
            except Exception as e:
                logger.warning("papkalarni yangilashda xato: %s: %s", type(e).__name__, e)
        c = rt.client
        if c is None:
            continue
        ok = None
        try:
            if not c.is_connected():
                logger.warning("Telethon ulanishi uzilgan — qayta ulanyapman")
                await c.connect()
            ok = bool(await asyncio.wait_for(c.is_user_authorized(), 30))
        except Exception as e:               # vaqtinchalik tarmoq xatosi — adminni bezovta qilmaymiz
            logger.warning("sessiya tekshiruvi xato: %s: %s", type(e).__name__, e)
        if ok is False and was_ok:
            logger.error("Telegram sessiyasi bekor qilingan")
            await rt.notify("✕ Telegram sessiyasi bekor qilingan — userbot postlarni ko'rmayapti.\n"
                            "Ko'pincha bir sessiya ikki joyda (masalan Railway va kompyuter) bir vaqtda ishlaganidan bo'ladi.\n"
                            "Faqat bitta nusxa qoldiring, /logout, so'ng /start bilan qayta ulang.")
        if ok is not None:
            was_ok = ok
