import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from database.engine import AsyncSessionLocal
from database.queries import get_active_channels
from utils.security import parse_admin_ids

# `parse_admin_ids` bo'sh ID'larni filtrlaydi — aks holda `""` qiymati
# admin ro'yxatida qoladi va kelajakdagi tekshiruvlarni xatolashtirishi mumkin.
ADMINS = parse_admin_ids(os.getenv("ADMIN_ID", ""))

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────
# Performance: SubscriptionMiddleware har bir xabar/callback uchun
# `get_active_channels` ni chaqiradi. 200k foydalanuvchi ko'lamida
# bu DB ga sekundiga yuzlab so'rov degani. Natija qisqa TTL xotira
# keshida saqlanadi. Admin kanal qo'shsa/o'chirsa
# `invalidate_active_channels_cache()` chaqiriladi.
# ───────────────────────────────────────────────────────────────
_ACTIVE_CHANNELS_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_ACTIVE_CHANNELS_TTL = 60.0  # soniya
_ACTIVE_CHANNELS_LOCK = asyncio.Lock()


async def _load_active_channels() -> list:
    """Baza'dan faol kanallarni oladi (keshsiz)."""
    async with AsyncSessionLocal() as session:
        return await get_active_channels(session)


async def get_cached_active_channels() -> list:
    """TTL kesh bilan faol kanallar ro'yxatini qaytaradi."""
    now = time.monotonic()
    data = _ACTIVE_CHANNELS_CACHE["data"]
    if data is not None and (now - _ACTIVE_CHANNELS_CACHE["ts"]) < _ACTIVE_CHANNELS_TTL:
        return data

    async with _ACTIVE_CHANNELS_LOCK:
        # double-check — boshqa coroutine allaqachon yangilagan bo'lishi mumkin
        now = time.monotonic()
        data = _ACTIVE_CHANNELS_CACHE["data"]
        if data is not None and (now - _ACTIVE_CHANNELS_CACHE["ts"]) < _ACTIVE_CHANNELS_TTL:
            return data
        fresh = await _load_active_channels()
        _ACTIVE_CHANNELS_CACHE["data"] = fresh
        _ACTIVE_CHANNELS_CACHE["ts"] = time.monotonic()
        return fresh


def invalidate_active_channels_cache() -> None:
    """Admin kanal qo'shgani/o'chirganida/yoqqanida chaqiriladi."""
    _ACTIVE_CHANNELS_CACHE["data"] = None
    _ACTIVE_CHANNELS_CACHE["ts"] = 0.0


def get_sub_keyboard(channels: list):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(text=f"📢 {ch.channel_name}", url=ch.channel_url)])
    buttons.append(
        [
            InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subs"),
            InlineKeyboardButton(text="❌ Chiqish", callback_data="cancel_sub_check"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _check_one(bot, user_id: int, ch) -> Any:
    """Bitta kanalga obuna tekshiruvi — timeout bilan himoyalangan."""
    if not ch.require_check or not ch.channel_id:
        return None
    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(chat_id=ch.channel_id, user_id=user_id),
            timeout=5.0,
        )
        if member.status in ("left", "kicked", "banned"):
            return ch
    except asyncio.TimeoutError:
        # Sekin/ishlamayotgan kanal — foydalanuvchini bloklamaymiz.
        logger.warning(
            "subscription: get_chat_member timed out channel=%s user=%s",
            getattr(ch, "channel_id", None), user_id,
        )
    except Exception:
        # Kanal o'chirilgan, bot admin emas va hokazo — bloklamaymiz.
        logger.debug(
            "subscription: get_chat_member failed channel=%s user=%s",
            getattr(ch, "channel_id", None), user_id, exc_info=True,
        )
    return None


async def check_subscription(bot, user_id: int, channels: list) -> list:
    """
    Faqat require_check=True va channel_id mavjud kanallarni tekshiradi.
    Qolganlar — faqat ko'rsatiladi, tekshirilmaydi.

    Tekshiruv parallel ravishda bajariladi — ketma-ket loop har kanal
    uchun Telegram API kechikishini user-kutish vaqtiga qo'shib yuboradi.
    """
    relevant = [ch for ch in channels if ch.require_check and ch.channel_id]
    if not relevant:
        return []
    results = await asyncio.gather(
        *(_check_one(bot, user_id, ch) for ch in relevant),
        return_exceptions=False,
    )
    return [ch for ch in results if ch is not None]


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[Any, dict], Awaitable[Any]], event: Any, data: dict) -> Any:
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        else:
            return await handler(event, data)

        # Admin — to'siqsiz
        if str(user.id) in ADMINS:
            return await handler(event, data)

        # Bu callbacklar — to'siqsiz
        if isinstance(event, CallbackQuery) and event.data in ("check_subs", "cancel_sub_check"):
            return await handler(event, data)

        try:
            channels = await get_cached_active_channels()
        except Exception:
            # DB vaqtinchalik yiqilgan bo'lsa — foydalanuvchini bloklamaslik
            # yaxshiroq, chunki bu UX uchun juda ko'rinadigan muammo.
            logger.exception("subscription: failed to load active channels")
            return await handler(event, data)

        if not channels:
            return await handler(event, data)

        bot = data.get("bot") or event.bot
        not_subbed = await check_subscription(bot, user.id, channels)

        if not_subbed:
            text = "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n" + "\n".join(
                f"• {ch.channel_name}" for ch in not_subbed
            )
            kb = get_sub_keyboard(not_subbed)
            if isinstance(event, Message):
                await event.answer(text, reply_markup=kb, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                try:
                    await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
                except Exception:
                    await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
                await event.answer()
            return

        return await handler(event, data)
