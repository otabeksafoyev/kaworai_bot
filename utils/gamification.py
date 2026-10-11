"""
utils/gamification.py — o'yin elementlari: daraja, ochko (XP), kunlik seriya, nishonlar.

Ochko:   qism ko'rish +10 (har bir noyob qism faqat bir marta), baho berish +5 (har bir kontentga bir marta),
         kunlik kirish +3, do'st taklif qilish +30.
Daraja:  Yangi (0) → Otaku (100) → Senpai (500) → Sensei (1500).
Seriya:  har kuni (O'zbekiston vaqti) kamida bir marta kirsa — +1 kun; bir kun o'tkazib yuborsa — qaytadan 1.
Hamma hodisalar "best-effort": xato bo'lsa asosiy ish (video ko'rsatish, baho berish) buzilmaydi.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from database.models import Anime, AnimeSubscription, User, UserEpisodeSeen
from data import config
from utils.ui import DIV1, DIV2, EFFECT_CONFETTI, current_bot, progress_bar, send_with_effect

logger = logging.getLogger(__name__)

ENABLED = bool(getattr(config, "GAMIFICATION_ENABLED", False))

XP_EPISODE = 10
XP_RATING = 5
XP_INVITE = 30
XP_DAILY = 3

# (nomi, belgisi, boshlanish ochkosi)
LEVELS = [("Yangi", "○", 0), ("Otaku", "✦", 100), ("Senpai", "✧", 500), ("Sensei", "◆", 1500)]

# kalit: (nomi, qanday olinadi)
BADGES: dict[str, tuple[str, str]] = {
    "first_ep": ("Birinchi qadam", "Birinchi qismni ko'ring"),
    "ep_10": ("Birinchi 10 qism", "10 ta qism ko'ring"),
    "ep_50": ("50 qism klubi", "50 ta qism ko'ring"),
    "ep_100": ("Marafonchi", "100 ta qism ko'ring"),
    "rate_5": ("Tanqidchi", "5 ta kontentga baho bering"),
    "rate_25": ("Ekspert", "25 ta kontentga baho bering"),
    "streak_3": ("3 kunlik seriya", "3 kun ketma-ket kiring"),
    "streak_7": ("Haftalik seriya", "7 kun ketma-ket kiring"),
    "streak_30": ("Oylik seriya", "30 kun ketma-ket kiring"),
    "fav_5": ("Kolleksioner", "5 ta kontentga obuna bo'ling"),
    "dorama_10": ("Dorama ixlosmandi", "10 ta dorama qismini ko'ring"),
    "night_owl": ("Tun boyqushi", "Tunda (00:00–05:00) qism ko'ring"),
    "invite_1": ("Do'st topdi", "1 ta do'st taklif qiling"),
    "invite_5": ("Jamoa quruvchi", "5 ta do'st taklif qiling"),
}

# user_id -> (sana, seriya) — bosh menyuda "ϟ 5 kun ketma-ket!" ni bazaga murojaatsiz ko'rsatish uchun
STREAK_CACHE: dict[int, tuple[date, int]] = {}
_BG_TASKS: set[asyncio.Task] = set()


# ─── Sof funksiyalar (testlash oson) ──────────────────────────────────

def uz_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=5)


def level_info(xp: int | None) -> tuple[int, str, str, int, int | None]:
    """(indeks, nomi, belgisi, boshlanish ochkosi, keyingi daraja ochkosi yoki None)."""
    xp = int(xp or 0)
    idx = 0
    for i, (_, _, floor) in enumerate(LEVELS):
        if xp >= floor:
            idx = i
    name, icon, floor = LEVELS[idx]
    nxt = LEVELS[idx + 1][2] if idx + 1 < len(LEVELS) else None
    return idx, name, icon, floor, nxt


def xp_bar(xp: int | None) -> tuple[str, str]:
    """(progress chizig'i, '310 / 500 XP' yoki 'MAX')."""
    xp = int(xp or 0)
    _, _, _, floor, nxt = level_info(xp)
    if nxt is None:
        return progress_bar(1, 1), f"{xp} XP · MAX"
    return progress_bar(xp - floor, nxt - floor), f"{xp} / {nxt} XP"


def earned_badges(stats: dict) -> list[str]:
    """Statistikaga ko'ra olingan nishon kalitlari (BADGES tartibida)."""
    s = {k: int(stats.get(k) or 0) for k in ("episodes", "ratings", "streak", "favs", "dorama_eps", "night", "invites")}
    cond = {
        "first_ep": s["episodes"] >= 1,
        "ep_10": s["episodes"] >= 10,
        "ep_50": s["episodes"] >= 50,
        "ep_100": s["episodes"] >= 100,
        "rate_5": s["ratings"] >= 5,
        "rate_25": s["ratings"] >= 25,
        "streak_3": s["streak"] >= 3,
        "streak_7": s["streak"] >= 7,
        "streak_30": s["streak"] >= 30,
        "fav_5": s["favs"] >= 5,
        "dorama_10": s["dorama_eps"] >= 10,
        "night_owl": s["night"] >= 1,
        "invite_1": s["invites"] >= 1,
        "invite_5": s["invites"] >= 5,
    }
    return [k for k in BADGES if cond.get(k)]


def streak_line(user_id: int) -> str:
    """Bosh menyu uchun: 'ϟ 5 kun ketma-ket!' (bugungi kesh bo'lsa va 2+ kun bo'lsa)."""
    item = STREAK_CACHE.get(user_id)
    if ENABLED and item and item[0] == uz_now().date() and item[1] >= 2:
        return f"ϟ <b>{item[1]} kun ketma-ket!</b>"
    return ""


def _level_up_text(name: str, icon: str, xp: int) -> str:
    bar, label = xp_bar(xp)
    return (
        f"{DIV1}\n{icon} <b>DARAJA OSHDI!</b>\n{DIV1}\n\n"
        f"Siz endi <b>{name}</b> bo'ldingiz!\n"
        f"{bar} {label}\n\n"
        f"{DIV2}\nᐅ Profilingiz: /profil"
    )


def _badges_text(keys: list[str]) -> str:
    lines = "\n".join(f"✦ <b>{BADGES[k][0]}</b>\n   <i>{BADGES[k][1]}</i>" for k in keys)
    title = "YANGI NISHON" if len(keys) == 1 else "YANGI NISHONLAR"
    return f"{DIV2}\n✦ <b>{title}</b>\n{DIV2}\n\n{lines}"


# ─── Xabar yuborish ───────────────────────────────────────────────────

def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


async def _send(bot, chat_id: int, text: str, effect: str | None) -> None:
    try:
        await send_with_effect(bot, chat_id, text, effect, parse_mode="HTML")
    except Exception:
        logger.info("gamification xabari yuborilmadi: %s", chat_id)


def _notify(user_id: int, old_level: int, user: User, new_badges: list[str]) -> None:
    bot = current_bot.get()
    if bot is None:
        return
    idx, name, icon, _, _ = level_info(user.xp)
    parts, effect = [], None
    if idx > old_level:
        parts.append(_level_up_text(name, icon, user.xp or 0))
        effect = EFFECT_CONFETTI
    if new_badges:
        parts.append(_badges_text(new_badges))
    if parts:
        _spawn(_send(bot, user_id, "\n\n".join(parts), effect))


# ─── Asosiy mexanizm ──────────────────────────────────────────────────

async def _grant(session, user_id: int, xp: int = 0, counters: dict | None = None, extra: dict | None = None) -> None:
    """XP va hisoblagichlarni atomik oshiradi, daraja/nishonlarni tekshiradi, kerak bo'lsa xabar yuboradi."""
    if not ENABLED:
        return
    user = await session.get(User, user_id)
    if user is None:
        return
    old_level = level_info(user.xp)[0]

    values = {"xp": func.coalesce(User.xp, 0) + xp}
    for field, delta in (counters or {}).items():
        values[field] = func.coalesce(getattr(User, field), 0) + delta
    await session.execute(update(User).where(User.telegram_id == user_id).values(**values))
    await session.commit()
    await session.refresh(user)

    stats = {
        "episodes": user.episodes_watched,
        "ratings": user.ratings_given,
        "streak": max(user.streak_days or 0, user.best_streak or 0),
        **(extra or {}),
    }
    have = list(user.achievements or [])
    new = [k for k in earned_badges(stats) if k not in have]
    if new:
        user.achievements = have + new  # yangi ro'yxat — SQLAlchemy o'zgarishni sezadi
        await session.commit()
    _notify(user_id, old_level, user, new)


async def touch_streak(session, user_id: int) -> int:
    """Kunlik seriyani yangilaydi (kuniga bir marta yozadi). Joriy seriyani qaytaradi."""
    if not ENABLED:
        return 0
    user = await session.get(User, user_id)
    if user is None:
        return 0
    today = uz_now().date()
    last = user.last_streak_date
    if last == today:
        STREAK_CACHE[user_id] = (today, user.streak_days or 0)
        return user.streak_days or 0
    streak = (user.streak_days or 0) + 1 if last == today - timedelta(days=1) else 1
    user.streak_days = streak
    user.best_streak = max(user.best_streak or 0, streak)
    user.last_streak_date = today
    await session.commit()
    STREAK_CACHE[user_id] = (today, streak)
    await _grant(session, user_id, XP_DAILY)
    return streak


# ─── Hodisalar (best-effort) ──────────────────────────────────────────

async def on_episode(session, user_id: int, anime_id: int, episode: int) -> None:
    if not ENABLED:
        return
    try:
        await touch_streak(session, user_id)
        seen = await session.execute(
            select(UserEpisodeSeen.id).where(
                UserEpisodeSeen.user_id == user_id,
                UserEpisodeSeen.anime_id == anime_id,
                UserEpisodeSeen.episode == episode,
            )
        )
        if seen.first():
            return  # takroriy ko'rish — ochko yo'q
        session.add(UserEpisodeSeen(user_id=user_id, anime_id=anime_id, episode=episode))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return
        extra = {"night": 1 if uz_now().hour < 5 else 0}
        anime = await session.get(Anime, anime_id)
        if anime is not None and anime.content_type == "dorama":
            extra["dorama_eps"] = (
                await session.execute(
                    select(func.count(UserEpisodeSeen.id))
                    .join(Anime, Anime.id == UserEpisodeSeen.anime_id)
                    .where(UserEpisodeSeen.user_id == user_id, Anime.content_type == "dorama")
                )
            ).scalar() or 0
        await _grant(session, user_id, XP_EPISODE, {"episodes_watched": 1}, extra)
    except Exception:
        logger.warning("on_episode xato", exc_info=True)
        try:
            await session.rollback()
        except Exception:
            pass


async def on_rating(session, user_id: int) -> None:
    """Kontentga BIRINCHI marta baho berilganda chaqiriladi."""
    if not ENABLED:
        return
    try:
        await _grant(session, user_id, XP_RATING, {"ratings_given": 1})
    except Exception:
        logger.warning("on_rating xato", exc_info=True)


async def on_favorite(session, user_id: int) -> None:
    """Obuna qo'shilganda — faqat nishon tekshiriladi (ochko yo'q: qayta-qayta bosib ochko yig'ib bo'lmasin)."""
    if not ENABLED:
        return
    try:
        favs = (
            await session.execute(select(func.count(AnimeSubscription.id)).where(AnimeSubscription.user_id == user_id))
        ).scalar() or 0
        await _grant(session, user_id, 0, None, {"favs": favs})
    except Exception:
        logger.warning("on_favorite xato", exc_info=True)


async def on_invite(session, user_id: int, invited_total: int) -> None:
    if not ENABLED:
        return
    try:
        await _grant(session, user_id, XP_INVITE, None, {"invites": invited_total})
    except Exception:
        logger.warning("on_invite xato", exc_info=True)
