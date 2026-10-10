"""handlers/profile.py — «✦ Mening profilim»: daraja, seriya, nishonlar."""

from __future__ import annotations

import html
from urllib.parse import quote

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.engine import AsyncSessionLocal
from database.models import User
from utils.gamification import BADGES, earned_badges, level_info, xp_bar
from utils.referral import referral_stats
from utils.ui import DIV1, DIV2, referral_link

profile_router = Router()


def _owned(user: User | None) -> list[str]:
    """Saqlangan nishonlar (BADGES tartibida)."""
    have = set((user.achievements if user else None) or [])
    return [k for k in BADGES if k in have]


async def _profile_view(tg_user: types.User) -> tuple[str, InlineKeyboardMarkup]:
    async with AsyncSessionLocal() as session:
        user = await session.get(User, tg_user.id)
    invited, _ = await referral_stats(tg_user.id)

    xp = (user.xp if user else 0) or 0
    _, level, icon, _, _ = level_info(xp)
    bar, bar_label = xp_bar(xp)
    owned = _owned(user)
    next_key = next((k for k in BADGES if k not in owned), None)

    lines = [
        DIV1,
        "✦ <b>MENING PROFILIM</b>",
        DIV1,
        "",
        f"☻ <b>{html.escape(tg_user.first_name or 'Foydalanuvchi')}</b>",
        f"{icon} Daraja: <b>{level}</b>",
        f"{bar} {bar_label}",
        "",
        f"ᐅ Ko'rilgan qismlar: <b>{(user.episodes_watched if user else 0) or 0}</b>",
        f"ᐅ Berilgan baholar: <b>{(user.ratings_given if user else 0) or 0}</b>",
        f"ϟ Seriya: <b>{(user.streak_days if user else 0) or 0} kun</b> (eng yaxshi: {(user.best_streak if user else 0) or 0})",
        f"ᐅ Taklif qilingan do'stlar: <b>{invited}</b>",
        "",
        DIV2,
        f"✦ Nishonlar: <b>{len(owned)}/{len(BADGES)}</b>",
    ]
    if owned:
        lines.append(", ".join(BADGES[k][0] for k in owned[:6]) + (" …" if len(owned) > 6 else ""))
    if next_key:
        lines.append(f"\n○ Keyingisi: <b>{BADGES[next_key][0]}</b> — <i>{BADGES[next_key][1]}</i>")

    share_text = f"Men Kaworai'da {level} darajasiga yetdim! {(user.episodes_watched if user else 0) or 0} qism ko'rdim."
    share_url = f"https://t.me/share/url?url={quote(referral_link(tg_user.id))}&text={quote(share_text)}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↗ Natijani ulashish", url=share_url)],
            [InlineKeyboardButton(text="✦ Barcha nishonlar", callback_data="my_badges")],
            [InlineKeyboardButton(text="⌂ Asosiy menyu", callback_data="main_menu")],
        ]
    )
    return "\n".join(lines), kb


async def _badges_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
    owned = set(_owned(user))
    lines = [DIV2, "✦ <b>NISHONLAR</b>", DIV2, ""]
    for key, (name, how) in BADGES.items():
        lines.append(f"✓ <b>{name}</b>" if key in owned else f"○ {name} — <i>{how}</i>")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ᐊ Profil", callback_data="my_profile")],
            [InlineKeyboardButton(text="⌂ Asosiy menyu", callback_data="main_menu")],
        ]
    )
    return "\n".join(lines), kb


async def _show(call: types.CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await call.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await call.message.answer(text, reply_markup=kb, parse_mode="HTML")


@profile_router.callback_query(F.data == "my_profile")
async def profile_cb(call: types.CallbackQuery):
    text, kb = await _profile_view(call.from_user)
    await _show(call, text, kb)
    await call.answer()


@profile_router.callback_query(F.data == "my_badges")
async def badges_cb(call: types.CallbackQuery):
    text, kb = await _badges_view(call.from_user.id)
    await _show(call, text, kb)
    await call.answer()


@profile_router.message(Command("profil"))
async def profile_cmd(message: types.Message):
    text, kb = await _profile_view(message.from_user)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
