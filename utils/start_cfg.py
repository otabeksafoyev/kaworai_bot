"""
utils/start_cfg.py — /start menyusi sozlamalari (admin boshqaradi).

Hammasi `bot_settings` jadvalida saqlanadi (yangi jadval / migratsiya kerak emas):
  start_photo    — /start rasmining Telegram file_id si (bo'lmasa standart rasm)
  start_buttons  — admin qo'shgan tugmalar, JSON ro'yxat:
      {"id": "a1b2c3d4", "label": "Pro haqida", "audience": "all|pro|user",
       "kind": "link"  → "url" bor: bosilganda havola o'zi ochiladi (bot javob yozmaydi)
       "kind": "reply" → "text" + "links": [{"label","url"}, ...]: bosilganda bot javob yozadi,
                         javobga istalgancha link-tugma qo'shish mumkin}
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from aiogram.types import InlineKeyboardButton
from sqlalchemy import delete, select

from database.engine import AsyncSessionLocal
from database.models import BotSetting, User
from utils.ui import sym

logger = logging.getLogger(__name__)

KEY_PHOTO = "start_photo"
KEY_BUTTONS = "start_buttons"

AUDIENCES = {"all": "Hamma uchun", "pro": "Faqat Pro", "user": "Faqat oddiy"}


async def _get(key: str) -> str | None:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
        return row.value if row and row.value else None


async def _set(key: str, value: str | None) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(BotSetting).where(BotSetting.key == key))
        if value:
            session.add(BotSetting(key=key, value=value))
        await session.commit()


# ─── Rasm ─────────────────────────────────────────────────────────────
async def get_start_photo() -> str | None:
    try:
        return await _get(KEY_PHOTO)
    except Exception:
        logger.warning("get_start_photo xato", exc_info=True)
        return None


async def set_start_photo(file_id: str | None) -> None:
    await _set(KEY_PHOTO, file_id)


# ─── Tugmalar ─────────────────────────────────────────────────────────
async def load_buttons() -> list[dict]:
    try:
        raw = await _get(KEY_BUTTONS)
        data = json.loads(raw) if raw else []
        return [b for b in data if isinstance(b, dict) and b.get("id") and b.get("label")]
    except Exception:
        logger.warning("start_buttons o'qishda xato", exc_info=True)
        return []


async def _save_buttons(buttons: list[dict]) -> None:
    await _set(KEY_BUTTONS, json.dumps(buttons, ensure_ascii=False) if buttons else None)


async def add_button(btn: dict) -> dict:
    btn = {**btn, "id": uuid.uuid4().hex[:8]}
    buttons = await load_buttons()
    buttons.append(btn)
    await _save_buttons(buttons)
    return btn


async def delete_button(btn_id: str) -> bool:
    buttons = await load_buttons()
    left = [b for b in buttons if b["id"] != btn_id]
    if len(left) == len(buttons):
        return False
    await _save_buttons(left)
    return True


async def get_button(btn_id: str) -> dict | None:
    return next((b for b in await load_buttons() if b["id"] == btn_id), None)


async def is_pro_user(user_id: int) -> bool:
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            return bool(user and user.is_pro and (not user.pro_until or user.pro_until > datetime.utcnow()))
    except Exception:
        return False


def audience_ok(btn: dict, is_pro: bool) -> bool:
    aud = btn.get("audience", "all")
    return aud == "all" or (aud == "pro" and is_pro) or (aud == "user" and not is_pro)


def to_inline(btn: dict) -> InlineKeyboardButton:
    """link → URL tugma (bosilganda o'zi ochiladi); reply → callback tugma."""
    text = sym(btn["label"])
    if btn.get("kind") == "link" and btn.get("url"):
        return InlineKeyboardButton(text=text, url=btn["url"])
    return InlineKeyboardButton(text=text, callback_data=f"sbtn_{btn['id']}")


async def custom_start_buttons(user_id: int) -> list[InlineKeyboardButton]:
    """Shu foydalanuvchiga ko'rinadigan (Pro/oddiy filtri bilan) admin tugmalari."""
    buttons = await load_buttons()
    if not buttons:
        return []
    is_pro = await is_pro_user(user_id) if user_id else False
    return [to_inline(b) for b in buttons if audience_ok(b, is_pro)]
