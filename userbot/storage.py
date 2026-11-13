"""Sozlamalar va sessiya — mavjud `bot_settings` jadvalida (Railway'da fayl o'chib ketadi, DB qoladi).
Sessiya Fernet bilan shifrlanadi."""
from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet
from sqlalchemy import select

from database.engine import AsyncSessionLocal
from database.models import BotSetting

_K_SESSION = "userbot:session"
_K_CREDS = "userbot:creds"
_K_WATCH = "userbot:watch"
_K_DONE = "userbot:done"
_K_TARGETS = "userbot:targets"


def _fernet() -> Fernet:
    key = os.environ.get("USERBOT_FERNET_KEY", "")
    if not key:
        raise RuntimeError("USERBOT_FERNET_KEY .env da yo'q (Fernet.generate_key() bilan yarating)")
    return Fernet(key.encode())


async def _get(key: str) -> str | None:
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
        return row.value if row else None


async def _set(key: str, value: str) -> None:
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
        if row:
            row.value = value
        else:
            s.add(BotSetting(key=key, value=value))
        await s.commit()


async def _del(key: str) -> None:
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
        if row:
            await s.delete(row)
            await s.commit()


async def save_login(api_id: int, api_hash: str, session_string: str) -> None:
    f = _fernet()
    await _set(_K_CREDS, f.encrypt(json.dumps({"api_id": api_id, "api_hash": api_hash}).encode()).decode())
    await _set(_K_SESSION, f.encrypt(session_string.encode()).decode())


async def load_login() -> tuple[int, str, str] | None:
    c, s = await _get(_K_CREDS), await _get(_K_SESSION)
    if not c or not s:
        return None
    f = _fernet()
    d = json.loads(f.decrypt(c.encode()))
    return int(d["api_id"]), d["api_hash"], f.decrypt(s.encode()).decode()


async def clear_login() -> None:
    for k in (_K_CREDS, _K_SESSION):
        await _del(k)


async def save_watch(cfg: dict) -> None:
    await _set(_K_WATCH, json.dumps(cfg))


async def load_watch() -> dict | None:
    v = await _get(_K_WATCH)
    return json.loads(v) if v else None


async def is_done(chat_id: int, msg_id: int) -> bool:
    v = json.loads(await _get(_K_DONE) or "[]")
    return f"{chat_id}:{msg_id}" in v


async def mark_done(chat_id: int, msg_id: int) -> None:
    v = json.loads(await _get(_K_DONE) or "[]")
    v.append(f"{chat_id}:{msg_id}")
    await _set(_K_DONE, json.dumps(v[-500:]))


# ── Nishon botlar (Kaworai / Yumora ...) ─────────────────────────────────────
# Har biri: {"id","kind","name","min_percent","enabled", ["secret" (Fernet), "bot_username"]}
# Bo'sh ro'yxat = eski (bitta Kaworai, admin tasdig'i bilan) rejim.
def seal(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def unseal(token: str) -> dict:
    return json.loads(_fernet().decrypt(token.encode()))


async def load_targets() -> list[dict]:
    v = await _get(_K_TARGETS)
    return json.loads(v) if v else []


async def save_targets(items: list[dict]) -> None:
    await _set(_K_TARGETS, json.dumps(items))
