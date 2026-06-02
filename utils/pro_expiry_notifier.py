"""
utils/pro_expiry_notifier.py — Pro obuna tugash eslatmasi scheduler

Har 12 soatda ishga tushadi va:
  - 3 kun qolgan foydalanuvchilarga ogohlantirish yuboradi
  - 1 kun qolgan foydalanuvchilarga oxirgi eslatma yuboradi
  - Muddati o'tganlarga pro o'chiriladi va xabar yuboriladi
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, select

from database.engine import AsyncSessionLocal
from database.models import User

logger = logging.getLogger(__name__)

# Eslatma yuborilgan userlarni kesh — restart bo'lsa qayta yuboradi,
# lekin bu 12 soatda bir marta ishlagani uchun muammo emas.
_notified_3d: set[int] = set()
_notified_1d: set[int] = set()


async def check_and_notify_pro_expiry(bot) -> None:
    """
    Pro tugashiga yaqin foydalanuvchilarga eslatma yuboradi.
    va muddati o'tganlarni avtomatik o'chiradi.
    """
    now = datetime.utcnow()
    three_days_later = now + timedelta(days=3)
    one_day_later = now + timedelta(days=1)

    async with AsyncSessionLocal() as session:
        # 1. Muddati o'tgan Pro foydalanuvchilar
        expired_result = await session.execute(
            select(User).where(
                and_(
                    User.is_pro == True,
                    User.pro_until != None,
                    User.pro_until < now,
                )
            )
        )
        expired_users = expired_result.scalars().all()

        for user in expired_users:
            try:
                user.is_pro = False
                user.pro_until = None
                await session.commit()

                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        "😔 <b>Kaworai Pro obunangiz tugadi.</b>\n\n"
                        "Pro imkoniyatlaridan foydalanishda davom etish uchun "
                        "obunani yangilang 👇\n\n"
                        "👉 /start → <b>💎 Kaworai Pro</b>"
                    ),
                    parse_mode="HTML",
                )
                logger.info("pro_expiry: user=%s Pro o'chirildi va xabar yuborildi", user.telegram_id)
            except Exception as e:
                logger.warning("pro_expiry: user=%s ga xabar yuborib bo'lmadi: %s", user.telegram_id, e)

        # 2. 3 kun qolganlar
        three_day_result = await session.execute(
            select(User).where(
                and_(
                    User.is_pro == True,
                    User.pro_until != None,
                    User.pro_until > now,
                    User.pro_until <= three_days_later,
                    User.pro_until > one_day_later,  # 1 kunliklarni exclude
                )
            )
        )
        three_day_users = three_day_result.scalars().all()

        for user in three_day_users:
            if user.telegram_id in _notified_3d:
                continue
            try:
                days_left = (user.pro_until - now).days + 1
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"⚠️ <b>Kaworai Pro obunangiz {days_left} kunda tugaydi!</b>\n\n"
                        f"📅 Tugash sanasi: <b>{user.pro_until.strftime('%d.%m.%Y')}</b>\n\n"
                        "Uzluksiz foydalanish uchun yangilang 👇\n"
                        "👉 /start → <b>💎 Kaworai Pro</b>"
                    ),
                    parse_mode="HTML",
                )
                _notified_3d.add(user.telegram_id)
                logger.info("pro_expiry: user=%s 3-kun eslatma yuborildi", user.telegram_id)
            except Exception as e:
                logger.warning("pro_expiry: user=%s ga 3-kun eslatma yuborib bo'lmadi: %s", user.telegram_id, e)

        # 3. 1 kun qolganlar
        one_day_result = await session.execute(
            select(User).where(
                and_(
                    User.is_pro == True,
                    User.pro_until != None,
                    User.pro_until > now,
                    User.pro_until <= one_day_later,
                )
            )
        )
        one_day_users = one_day_result.scalars().all()

        for user in one_day_users:
            if user.telegram_id in _notified_1d:
                continue
            try:
                hours_left = max(int((user.pro_until - now).total_seconds() / 3600), 1)
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"🚨 <b>Kaworai Pro obunangiz {hours_left} soatda tugaydi!</b>\n\n"
                        f"📅 Tugash sanasi: <b>{user.pro_until.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
                        "⚡ Hoziroq yangilang — Pro imkoniyatlaringizni yo'qotmang!\n"
                        "👉 /start → <b>💎 Kaworai Pro</b>"
                    ),
                    parse_mode="HTML",
                )
                _notified_1d.add(user.telegram_id)
                logger.info("pro_expiry: user=%s 1-kun eslatma yuborildi", user.telegram_id)
            except Exception as e:
                logger.warning("pro_expiry: user=%s ga 1-kun eslatma yuborib bo'lmadi: %s", user.telegram_id, e)


async def pro_expiry_loop(bot) -> None:
    """
    Har 12 soatda Pro tugash tekshiruvini ishga tushiradi.
    bot.py dagi on_startup() dan chaqiriladi.
    """
    logger.info("pro_expiry_loop: ishga tushdi")
    while True:
        try:
            await check_and_notify_pro_expiry(bot)
        except Exception:
            logger.exception("pro_expiry_loop: tekshiruvda xato")
        # 12 soatda bir tekshirish
        await asyncio.sleep(12 * 3600)
