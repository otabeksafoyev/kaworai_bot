# database/queries/partners.py
# Partner model yo'q — queries.py dagi Admin(role='partner') tizimi ishlatiladi

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Admin, User


# ===== PARTNER QUERIES =====
# Hamkorlar Admin jadvalida role='partner' sifatida saqlanadi.
# Alohida Partner modeli yo'q — queries.py dagi funksiyalarni ishlatamiz.


async def get_active_partners(session: AsyncSession) -> list[Admin]:
    """Barcha aktiv hamkorlarni olish (role='partner')"""
    result = await session.execute(select(Admin).where(Admin.role == "partner"))
    return result.scalars().all()


async def add_partner(session: AsyncSession, channel_id: int, channel_name: str, channel_url: str) -> Admin | None:
    """Yangi hamkor qo'shish — faqat Admin(role=partner) orqali ishlaydi.
    Bu funksiya muvofiqlik uchun saqlanadi, lekin telegram_id kerak.
    """
    # Bu funksiya eski interfeysni saqlaydi — channel_id bu yerda telegram_id
    existing = (await session.execute(select(Admin).where(Admin.telegram_id == channel_id))).scalar_one_or_none()
    if existing:
        existing.role = "partner"
        existing.nickname = channel_name
        await session.commit()
        return existing
    row = Admin(telegram_id=channel_id, nickname=channel_name, role="partner")
    session.add(row)
    await session.commit()
    return row


async def remove_partner(session: AsyncSession, channel_id: int) -> bool:
    """Hamkorni o'chirish"""
    result = await session.execute(delete(Admin).where(Admin.telegram_id == channel_id, Admin.role == "partner"))
    await session.commit()
    return result.rowcount > 0


async def get_all_partners(session: AsyncSession) -> list[Admin]:
    """Admin uchun — barcha hamkorlar"""
    result = await session.execute(select(Admin).where(Admin.role == "partner"))
    return result.scalars().all()


async def toggle_partner(session: AsyncSession, channel_id: int) -> bool | None:
    """Hamkorni topib qaytaradi yoki None"""
    result = await session.execute(
        select(Admin).where(Admin.telegram_id == channel_id, Admin.role == "partner")
    )
    partner = result.scalar_one_or_none()
    if not partner:
        return None
    # Admin modelida is_active yo'q — partner mavjudligini qaytaramiz
    return True


# ===== USER QUERIES =====


async def get_or_create_user(
    session: AsyncSession, user_id: int, username: str | None, full_name: str, ref_by: int | None = None
) -> tuple[User, bool]:
    """Foydalanuvchini olish yoki yaratish. (user, is_new) qaytaradi"""
    result = await session.execute(select(User).where(User.telegram_id == user_id))
    user = result.scalar_one_or_none()
    if user:
        return user, False

    user = User(telegram_id=user_id, username=username, full_name=full_name)
    session.add(user)
    await session.commit()
    return user, True


async def get_user_count(session: AsyncSession) -> int:
    """Jami foydalanuvchilar soni"""
    from sqlalchemy import func

    result = await session.execute(select(func.count(User.telegram_id)))
    return result.scalar()
