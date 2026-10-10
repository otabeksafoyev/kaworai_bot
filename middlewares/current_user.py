"""Joriy foydalanuvchi ID sini contextvar'ga qo'yadi (ulashish havolalariga taklif ID qo'shish uchun)."""

from aiogram import BaseMiddleware

from utils.ui import current_user_id


class CurrentUserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        token = current_user_id.set(user.id if user and not user.is_bot else None)
        try:
            return await handler(event, data)
        finally:
            current_user_id.reset(token)
