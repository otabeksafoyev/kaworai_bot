"""
utils/pro_utils.py — Pro tekshiruvi uchun markaziy utility

Muammo: handlers/genres.py, handlers/users_pro.py, handlers/pro_payment.py
va boshqa fayllarda pro tekshiruvi alohida yozilgan edi (copy-paste).
Endi faqat shu fayldan import qilinadi.
"""

from __future__ import annotations

from datetime import datetime


async def is_pro_active(user_id: int) -> bool:
    """
    Foydalanuvchining Pro obunasi hozir faolmi?

    - is_pro=False → False
    - pro_until < hozir → Pro o'chiriladi va False qaytadi
    - pro_until=None (cheksiz Pro) → True
    - pro_until > hozir → True

    Barcha handlerlarda shu funksiyadan foydalaning.
    """
    from database.engine import AsyncSessionLocal
    from database.models import User

    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.is_pro:
            return False
        if user.pro_until and user.pro_until < datetime.utcnow():
            # Muddati o'tgan — avtomatik o'chirish
            user.is_pro = False
            user.pro_until = None
            await session.commit()
            return False
        return True


async def get_pro_until_str(user_id: int) -> str | None:
    """Pro tugash sanasini 'dd.mm.yyyy' formatida qaytaradi. Pro yo'q bo'lsa None."""
    from database.engine import AsyncSessionLocal
    from database.models import User

    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.is_pro:
            return None
        if user.pro_until:
            return user.pro_until.strftime("%d.%m.%Y")
        return "♾ Cheksiz"


async def days_until_pro_expires(user_id: int) -> int | None:
    """
    Pro tugashiga necha kun qolganini qaytaradi.
    Pro yo'q yoki muddatsiz bo'lsa None.
    """
    from database.engine import AsyncSessionLocal
    from database.models import User

    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.is_pro or not user.pro_until:
            return None
        delta = user.pro_until - datetime.utcnow()
        return max(delta.days, 0)
