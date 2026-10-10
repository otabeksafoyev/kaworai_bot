"""
Joriy foydalanuvchi ID va botni contextvar'ga qo'yadi (ulashish havolalari, o'yin xabarlari uchun)
va qism ochadigan tugma bosilganda «video yuklanmoqda...» ko'rsatkichini yoqadi.
"""

import asyncio
import logging

from aiogram import BaseMiddleware

from utils.ui import current_bot, current_user_id

logger = logging.getLogger(__name__)
_BG: set[asyncio.Task] = set()


def _fire(coro) -> None:
    """Javobni kutmasdan yuboriladi — asosiy ishni sekinlashtirmaydi."""
    task = asyncio.create_task(coro)
    _BG.add(task)
    task.add_done_callback(_BG.discard)


async def _safe_action(bot, chat_id: int, action: str) -> None:
    try:
        await bot.send_chat_action(chat_id, action)
    except Exception:
        pass


def _opens_episode(data: str | None) -> bool:
    return bool(data) and (data.startswith("watch_start_") or (data.startswith("ep_") and data != "ep_noop"))


class CurrentUserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        bot = data.get("bot")
        t1 = current_user_id.set(user.id if user and not user.is_bot else None)
        t2 = current_bot.set(bot)
        try:
            cq = getattr(event, "callback_query", None)
            if bot and cq and cq.message and _opens_episode(cq.data):
                _fire(_safe_action(bot, cq.message.chat.id, "upload_video"))
            return await handler(event, data)
        finally:
            current_user_id.reset(t1)
            current_bot.reset(t2)
