"""
utils/referral.py — referal tizimi.

Oqim:
  1) A o'z havolasini (yoki ulashilgan anime havolasini) do'stiga yuboradi: ?start=ref_A / anime_ID_rA
  2) Yangi foydalanuvchi B /start bosadi → User.referred_by = A (faqat YANGI foydalanuvchi uchun)
  3) B majburiy kanallarga obuna bo'lib botga kirgach → A ga REFERRAL_REWARD_DAYS kun Pro beriladi
Himoya: o'zini taklif qilish yo'q; bir kishi uchun bir marta; bitta taklif qiluvchiga REFERRAL_MAX_REWARDS chegarasi.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update

from data import config
from database.engine import AsyncSessionLocal
from database.models import User

logger = logging.getLogger(__name__)

REWARD_DAYS = int(getattr(config, "REFERRAL_REWARD_DAYS", 3))
MAX_REWARDS = int(getattr(config, "REFERRAL_MAX_REWARDS", 30))


async def register_referral(session, new_user_id: int, referrer_id: int | None) -> bool:
    """Yangi foydalanuvchini taklif qiluvchiga bog'laydi. Bog'langan bo'lsa True."""
    if not referrer_id or referrer_id == new_user_id:
        return False
    if await session.get(User, referrer_id) is None:
        return False
    user = await session.get(User, new_user_id)
    if user is None or user.referred_by:
        return False
    user.referred_by = referrer_id
    user.referral_rewarded = False
    await session.commit()
    return True


async def reward_referrer_if_due(bot, user_id: int) -> bool:
    """Taklif qilingan foydalanuvchi to'liq kirgach — taklif qiluvchiga Pro kunlarini beradi."""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.referred_by:
            return False
        referrer_id = user.referred_by

        # Atomik belgilash — ikki marta bosilsa ham bir marta mukofot
        res = await session.execute(
            update(User)
            .where(
                User.telegram_id == user_id,
                or_(User.referral_rewarded.is_(False), User.referral_rewarded.is_(None)),
            )
            .values(referral_rewarded=True)
        )
        if res.rowcount != 1:
            await session.rollback()
            return False

        referrer = await session.get(User, referrer_id)
        if referrer is None:
            await session.commit()
            return False

        earned = (
            await session.execute(
                select(func.count(User.telegram_id)).where(
                    User.referred_by == referrer_id, User.referral_rewarded.is_(True)
                )
            )
        ).scalar() or 0
        if earned > MAX_REWARDS:
            await session.commit()
            return False

        now = datetime.utcnow()
        base = referrer.pro_until if (referrer.pro_until and referrer.pro_until > now) else now
        referrer.pro_until = base + timedelta(days=REWARD_DAYS)
        referrer.is_pro = True
        await session.commit()
        until_str = referrer.pro_until.strftime("%d.%m.%Y")

    try:
        await bot.send_message(
            referrer_id,
            f"🎉 <b>Do'stingiz botga qo'shildi!</b>\n\n"
            f"🎁 Sizga <b>{REWARD_DAYS} kun Kaworai Pro</b> sovg'a qilindi.\n"
            f"📅 Pro tugash sanasi: <b>{until_str}</b>",
            parse_mode="HTML",
        )
    except Exception:
        logger.info("referal xabari yuborilmadi: %s", referrer_id)
    logger.info("referral reward: referrer=%s invited=%s days=%s", referrer_id, user_id, REWARD_DAYS)
    return True


async def referral_stats(user_id: int) -> tuple[int, int]:
    """(taklif qilinganlar soni, mukofot olingani soni)."""
    async with AsyncSessionLocal() as session:
        invited = (
            await session.execute(select(func.count(User.telegram_id)).where(User.referred_by == user_id))
        ).scalar() or 0
        rewarded = (
            await session.execute(
                select(func.count(User.telegram_id)).where(
                    User.referred_by == user_id, User.referral_rewarded.is_(True)
                )
            )
        ).scalar() or 0
    return int(invited), min(int(rewarded), MAX_REWARDS)
