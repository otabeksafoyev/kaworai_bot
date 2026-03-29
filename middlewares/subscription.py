from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from database.engine import AsyncSessionLocal
from database.queries import get_active_channels
import os

ADMINS = os.getenv("ADMIN_ID", "").split(",")


def get_sub_keyboard(channels: list):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    for ch in channels:
        buttons.append([
            InlineKeyboardButton(text=f"📢 {ch.channel_name}", url=ch.channel_url)
        ])
    buttons.append([
        InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subs"),
        InlineKeyboardButton(text="❌ Chiqish", callback_data="cancel_sub_check"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def check_subscription(bot, user_id: int, channels: list) -> list:
    """
    Faqat require_check=True va channel_id mavjud kanallarni tekshiradi.
    Qolganlar — faqat ko'rsatiladi, tekshirilmaydi.
    """
    not_subbed = []
    for ch in channels:
        if not ch.require_check or not ch.channel_id:
            # Tekshiruv kerak emas — o'tkazib yuborish
            continue
        try:
            member = await bot.get_chat_member(chat_id=ch.channel_id, user_id=user_id)
            if member.status in ("left", "kicked", "banned"):
                not_subbed.append(ch)
        except Exception:
            continue
    return not_subbed


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict], Awaitable[Any]],
        event: Any,
        data: dict
    ) -> Any:
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

        async with AsyncSessionLocal() as session:
            channels = await get_active_channels(session)

        if not channels:
            return await handler(event, data)

        bot = data.get("bot") or event.bot
        not_subbed = await check_subscription(bot, user.id, channels)

        if not_subbed:
            text = (
                "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
                + "\n".join(f"• {ch.channel_name}" for ch in not_subbed)
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