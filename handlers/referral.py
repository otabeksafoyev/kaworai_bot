"""handlers/referral.py — «✦ Do'st taklif qilish» bo'limi."""

from __future__ import annotations

from urllib.parse import quote

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.referral import MAX_REWARDS, REWARD_DAYS, referral_stats
from utils.ui import referral_link

referral_router = Router()


async def _build(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    link = referral_link(user_id)
    invited, rewarded = await referral_stats(user_id)
    share_text = quote("๏ Kaworai — anime va dorama botiga qo'shiling!")
    text = (
        "✦ <b>Do'st taklif qilish</b>\n"
        "✧───────✧\n"
        f"Do'stingiz sizning havolangiz orqali botga kirsa, siz <b>{REWARD_DAYS} kun Kaworai Pro</b> olasiz!\n\n"
        f"↗ <b>Sizning havolangiz:</b>\n<code>{link}</code>\n\n"
        f"◉ Taklif qilganlar: <b>{invited}</b>\n"
        f"✓ Mukofot olingan: <b>{rewarded}</b> (≈ {rewarded * REWARD_DAYS} kun Pro)\n\n"
        f"<i>Mukofot do'stingiz kanallarga obuna bo'lib botga kirgach beriladi. "
        f"Eng ko'pi bilan {MAX_REWARDS} ta taklif uchun.</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↗ Do'stga yuborish", url=f"https://t.me/share/url?url={quote(link)}&text={share_text}")],
            [InlineKeyboardButton(text="⌂ Asosiy menyu", callback_data="main_menu")],
        ]
    )
    return text, kb


@referral_router.callback_query(F.data == "referral")
async def referral_cb(call: types.CallbackQuery):
    text, kb = await _build(call.from_user.id)
    try:
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await call.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


@referral_router.message(Command("taklif"))
async def referral_cmd(message: types.Message):
    text, kb = await _build(message.from_user.id)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
