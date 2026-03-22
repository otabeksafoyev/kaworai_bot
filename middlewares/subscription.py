from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.utils.markdown import hbold

from config import config
from database.models import SubscriptionChannel
from sqlalchemy import select

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user_id = event.from_user.id if hasattr(event, "from_user") else None
        if not user_id:
            return await handler(event, data)

        # Owner va adminlarga cheklov yo‘q
        if user_id == config.ADMIN_ID or await is_admin(user_id):
            return await handler(event, data)

        not_subscribed = []
        async with AsyncSession() as session:
            channels = await session.scalars(select(SubscriptionChannel).where(SubscriptionChannel.is_active))
            for ch in channels:
                try:
                    member = await bot.get_chat_member(ch.channel_id, user_id)
                    if member.status in ("left", "kicked"):
                        not_subscribed.append(ch)
                except:
                    pass  # kanal o‘chirilgan bo‘lishi mumkin

        if not_subscribed:
            text = "Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:\n\n"
            kb = []
            for ch in not_subscribed:
                text += f"• {ch.username or ch.channel_id}\n"
                kb.append([InlineKeyboardButton(text=f"Obuna bo‘lish →", url=f"https://t.me/{ch.username.lstrip('@')}")])
            kb.append([InlineKeyboardButton(text="Tekshirish", callback_data="check_sub")])

            if isinstance(event, Message):
                await event.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), disable_web_page_preview=True)
            elif isinstance(event, CallbackQuery):
                await event.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            return

        return await handler(event, data)