"""Telegram papkasi (addlist havolasi): ichidagi kanallarni topadi va "yangi qism" rejimida kuzatuvga qo'shadi.

Papka kanallaridagi postlar uchun userbot: postdagi tugmadan manba botga kiradi (kerak bo'lsa majburiy obunaga a'zo bo'ladi) va
Kaworai/Yumora bazasida BOR animening faqat YETISHMAYOTGAN qismlarini olib, botga qo'shadi va news kanallarga e'lon qiladi."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time

from telethon import errors, utils
from telethon.tl import types as T
from telethon.tl.functions.chatlists import CheckChatlistInviteRequest, JoinChatlistInviteRequest

from . import storage

logger = logging.getLogger("userbot")

MAX_FLOOD = int(os.environ.get("UB_MAX_FLOOD", "300"))
_ADDLIST_RE = re.compile(r"(?i)(?:https?://)?(?:t|telegram)\.me/addlist/([\w\-]+)")


def parse_addlist(text: str) -> str | None:
    m = _ADDLIST_RE.search(text or "")
    return m.group(1) if m else None


def _is_broadcast(chat) -> bool:
    return isinstance(chat, T.Channel) and bool(getattr(chat, "broadcast", False))


def _split_peers(res, stored_title: str | None = None) -> tuple[str, list[dict], list[dict]]:
    """(papka nomi, a'zo bo'lingan kanallar, hali a'zo bo'linmagan kanallar) — faqat kanallar (broadcast)."""
    chats = {c.id: c for c in getattr(res, "chats", []) if hasattr(c, "id")}

    def pack(peers) -> list[dict]:
        out = []
        for p in peers or []:
            cid = getattr(p, "channel_id", None)
            ch = chats.get(cid)
            if cid is not None and ch is not None and _is_broadcast(ch):
                out.append({"id": cid, "title": getattr(ch, "title", None) or str(cid)})
        return out

    if isinstance(res, T.chatlists.ChatlistInviteAlready):
        return stored_title or "Papka", pack(res.already_peers), pack(res.missing_peers)
    title = getattr(getattr(res, "title", None), "text", None) or stored_title or "Papka"
    return title, [], pack(res.peers)


async def resolve(client, slug: str, stored_title: str | None = None) -> dict:
    res = await client(CheckChatlistInviteRequest(slug=slug))
    title, have, missing = _split_peers(res, stored_title)
    return {"slug": slug, "title": title, "channels": have, "missing": missing, "updated": time.time()}


async def add_folder(client, slug: str) -> dict:
    items = await storage.load_folders()
    old = next((f for f in items if f["slug"] == slug), None)
    folder = await resolve(client, slug, old["title"] if old else None)
    await storage.save_folders([f for f in items if f["slug"] != slug] + [folder])
    return folder


async def remove_folder(slug: str) -> None:
    await storage.save_folders([f for f in await storage.load_folders() if f["slug"] != slug])


async def refresh_all(client) -> bool:
    """Saqlangan papkalarni qayta o'qiydi (yangi kanallar qo'shilgan bo'lishi mumkin). O'zgargan bo'lsa True."""
    items = await storage.load_folders()
    changed = False
    for i, f in enumerate(items):
        try:
            nf = await resolve(client, f["slug"], f["title"])
        except Exception as e:
            logger.warning("papka %s yangilanmadi: %s: %s", f["slug"], type(e).__name__, e)
            continue
        if {c["id"] for c in nf["channels"]} != {c["id"] for c in f["channels"]} or len(nf["missing"]) != len(f.get("missing", [])):
            changed = True
        items[i] = nf
    if items:
        await storage.save_folders(items)
    return changed


async def join_missing(client, slug: str, notify=None) -> int:
    """Papkadagi hali a'zo bo'linmagan kanallarga a'zo bo'ladi. Nechta kanalga a'zo bo'lingani qaytariladi."""
    res = await client(CheckChatlistInviteRequest(slug=slug))
    chats = {c.id: c for c in getattr(res, "chats", []) if hasattr(c, "id")}
    peers = res.missing_peers if isinstance(res, T.chatlists.ChatlistInviteAlready) else res.peers
    inputs = [utils.get_input_peer(chats[p.channel_id]) for p in peers
              if getattr(p, "channel_id", None) in chats and _is_broadcast(chats[p.channel_id])]
    if not inputs:
        return 0
    for attempt in range(2):
        try:
            await client(JoinChatlistInviteRequest(slug=slug, peers=inputs))
            return len(inputs)
        except errors.FloodWaitError as e:
            if attempt == 0 and e.seconds <= MAX_FLOOD:
                if notify:
                    await notify(f"◌ Telegram {e.seconds}s kutishni so'radi — kutib, qayta uriniladi.")
                await asyncio.sleep(e.seconds + 1)
                continue
            raise
    return 0


def watch_map(folders: list[dict], skip: set[int]) -> dict[int, dict]:
    """Kuzatiladigan papka kanallari: {kanal_id: cfg}. Alohida kuzatilayotgan (to'liq rejim) kanallar o'tkazib yuboriladi."""
    out: dict[int, dict] = {}
    for f in folders:
        for ch in f.get("channels", []):
            if ch["id"] not in skip and ch["id"] not in out:
                out[ch["id"]] = {"channel": ch["id"], "title": ch["title"], "mode": "folder", "folder": f["title"]}
    return out
