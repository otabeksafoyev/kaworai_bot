"""Boshqaruv botidagi /targets bo'limi: nishon botlarni qo'shish, foizini belgilash, yoqish/o'chirish.
Yumora-uslubidagi bot ma'lumotlari (token, baza, kanal) shu yerda kiritiladi va Fernet bilan shifrlab saqlanadi."""
from __future__ import annotations

import html
import logging
import secrets

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import storage, targets
from .login_bot import DIV, _wipe
from .runtime import rt

logger = logging.getLogger("userbot")
router = Router()


class AddTarget(StatesGroup):
    name = State()
    token = State()
    dsn = State()
    chan = State()
    percent = State()


class SetPct(StatesGroup):
    value = State()


def _is_admin(uid: int) -> bool:
    return uid == rt.admin_id


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


async def _current() -> list[dict]:
    items = await targets.load_targets()
    return items or [dict(targets.DEFAULT_KAWORAI)]


def _parse_percent(text: str) -> int | None:
    t = (text or "").strip().rstrip("%").strip()
    return int(t) if t.isdigit() and 1 <= int(t) <= 100 else None


async def _list_view() -> tuple[str, InlineKeyboardMarkup]:
    saved = await storage.load_targets()
    if not saved:
        text = (f"{DIV}\n◈ <b>Nishon botlar</b>\n\nHozir <b>eski rejim</b>: har bir yangi post Kaworai ga "
                "faqat sizning tasdig'ingiz bilan qo'shiladi.\n\n"
                "Avtomatik rejimda AI natijasi adminga ko'rsatilmaydi: moslik foizi har bir botning chegarasidan "
                f"kam bo'lmasa o'sha botga qo'shiladi.\n{DIV}")
        kb = [[_btn("✓ Avtomatik rejimni yoqish (Kaworai 70%)", "tg:auto")],
              [_btn("＋ Yumora-uslubidagi bot qo'shish", "tg:add")]]
        return text, InlineKeyboardMarkup(inline_keyboard=kb)
    items = await targets.load_targets()
    lines = [f"{DIV}\n◈ <b>Nishon botlar</b> (avtomatik rejim)\n"]
    kb = []
    for t in items:
        mark = "✓" if t.get("enabled", True) else "✕"
        lines.append(f"{mark} <b>{html.escape(t['name'])}</b> — {t['min_percent']}%  ({t['kind']})")
        kb.append([_btn(f"{mark} {t['name']} — {t['min_percent']}%", f"tg:open:{t['id']}")])
    lines.append(f"\nFoiz — post/manba ma'lumoti AI natijasiga qanchalik mos kelishi (nom, yil, janr, tavsif).\n{DIV}")
    kb.append([_btn("＋ Yumora-uslubidagi bot qo'shish", "tg:add")])
    kb.append([_btn("↺ Eski rejimga qaytish", "tg:legacy")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


def _panel_view(t: dict) -> tuple[str, InlineKeyboardMarkup]:
    on = t.get("enabled", True)
    extra = f"\n@{html.escape(t['bot_username'])}" if t.get("bot_username") else ""
    only = "\nFaqat anime qabul qiladi." if t["kind"] == "yumora" else "\nAnime, dorama, serial, kino."
    text = (f"{DIV}\n◈ <b>{html.escape(t['name'])}</b>  ({t['kind']}){extra}\n"
            f"% Chegara: <b>{t['min_percent']}%</b>\nHolat: {'✓ yoqilgan' if on else '✕ o‘chirilgan'}{only}\n{DIV}")
    kb = [[_btn("% Foizni o'zgartirish", f"tg:pct:{t['id']}")],
          [_btn("✕ O'chirish" if on else "✓ Yoqish", f"tg:tog:{t['id']}")]]
    if t["kind"] != "kaworai":
        kb.append([_btn("🗑 Butunlay olib tashlash", f"tg:del:{t['id']}")])
    kb.append([_btn("← Orqaga", "tg:list")])
    return text, InlineKeyboardMarkup(inline_keyboard=kb)


async def _show(call: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("targets"))
async def targets_cmd(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    await state.clear()
    text, kb = await _list_view()
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "tg:list")
async def cb_list(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    await state.clear()
    text, kb = await _list_view()
    await _show(call, text, kb)
    await call.answer()


@router.callback_query(F.data == "tg:auto")
async def cb_auto(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    await storage.save_targets([dict(targets.DEFAULT_KAWORAI)])
    text, kb = await _list_view()
    await _show(call, text, kb)
    await call.answer("✓ Avtomatik rejim yoqildi")


@router.callback_query(F.data == "tg:legacy")
async def cb_legacy(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    for t in await storage.load_targets():
        await targets.forget(t["id"])
    await storage.save_targets([])
    text, kb = await _list_view()
    await _show(call, text, kb)
    await call.answer("✓ Eski rejim")


@router.callback_query(F.data.startswith("tg:open:"))
async def cb_open(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    tid = call.data.split(":", 2)[2]
    t = next((x for x in await targets.load_targets() if x["id"] == tid), None)
    if not t:
        return await call.answer("Topilmadi", show_alert=True)
    text, kb = _panel_view(t)
    await _show(call, text, kb)
    await call.answer()


@router.callback_query(F.data.startswith("tg:tog:"))
async def cb_toggle(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    tid = call.data.split(":", 2)[2]
    items = await _current()
    for t in items:
        if t["id"] == tid:
            t["enabled"] = not t.get("enabled", True)
            await storage.save_targets(items)
            text, kb = _panel_view(t)
            await _show(call, text, kb)
            return await call.answer("✓")
    await call.answer("Topilmadi", show_alert=True)


@router.callback_query(F.data.startswith("tg:del:"))
async def cb_delete(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    tid = call.data.split(":", 2)[2]
    items = [t for t in await _current() if t["id"] != tid or t["kind"] == "kaworai"]
    await storage.save_targets(items)
    await targets.forget(tid)
    text, kb = await _list_view()
    await _show(call, text, kb)
    await call.answer("✓ Olib tashlandi")


# ── foizni o'zgartirish ──────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("tg:pct:"))
async def cb_pct(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    await state.set_state(SetPct.value)
    await state.update_data(tid=call.data.split(":", 2)[2])
    await call.message.answer("% Yangi chegarani yuboring (1–100, masalan 70):")
    await call.answer()


@router.message(StateFilter(SetPct.value), F.text)
async def got_pct(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    pct = _parse_percent(msg.text)
    if pct is None:
        return await msg.answer("✕ 1 dan 100 gacha raqam yuboring.")
    tid = (await state.get_data())["tid"]
    items = await _current()
    for t in items:
        if t["id"] == tid:
            t["min_percent"] = pct
    await storage.save_targets(items)
    await state.clear()
    text, kb = await _list_view()
    await msg.answer(f"✓ Chegara {pct}% qilindi.\n\n{text}", parse_mode="HTML", reply_markup=kb)


# ── Yumora-uslubidagi bot qo'shish ───────────────────────────────────────────
@router.callback_query(F.data == "tg:add")
async def cb_add(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    if not rt.client:
        return await call.answer("Avval /start bilan akkauntni ulang.", show_alert=True)
    await state.set_state(AddTarget.name)
    await call.message.answer(f"{DIV}\n＋ <b>Yangi bot</b>\n\nBotga o'zingiz uchun nom bering (masalan: Yumora).\nBekor qilish: /cancel\n{DIV}",
                              parse_mode="HTML")
    await call.answer()


@router.message(StateFilter(AddTarget.name), F.text)
async def add_name(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    name = msg.text.strip()[:40]
    if not name or name.startswith("/"):
        return await msg.answer("✕ Nom yuboring.")
    await state.update_data(name=name)
    await state.set_state(AddTarget.token)
    await msg.answer("# Shu botning <b>BOT_TOKEN</b> ini yuboring (xabar o'chiriladi):", parse_mode="HTML")


@router.message(StateFilter(AddTarget.token), F.text)
async def add_token(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    token = msg.text.strip()
    await _wipe(msg)
    from aiogram import Bot
    bot = Bot(token)
    try:
        me = await bot.get_me()
    except Exception:
        return await msg.answer("✕ Token noto'g'ri. Qayta yuboring.")
    finally:
        await bot.session.close()
    await state.update_data(bot_token=token, bot_username=me.username)
    await state.set_state(AddTarget.dsn)
    await msg.answer(f"✓ Bot: @{me.username}\n\n▣ Shu botning <b>DATABASE_URL</b> ini yuboring (xabar o'chiriladi):",
                     parse_mode="HTML")


@router.message(StateFilter(AddTarget.dsn), F.text)
async def add_dsn(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    dsn = msg.text.strip()
    await _wipe(msg)
    import asyncpg
    try:
        conn = await asyncpg.connect(targets._dsn(dsn), timeout=15)
    except Exception as e:
        return await msg.answer(f"✕ Bazaga ulanib bo'lmadi: {type(e).__name__}\nQayta yuboring yoki /cancel")
    try:
        ok = await conn.fetchval("SELECT to_regclass('public.animes') IS NOT NULL AND to_regclass('public.episodes') IS NOT NULL")
    finally:
        await conn.close()
    if not ok:
        return await msg.answer("✕ Bazada animes/episodes jadvallari yo'q. Avval o'sha botni bir marta ishga tushiring.")
    await state.update_data(database_url=dsn)
    await state.set_state(AddTarget.chan)
    await msg.answer("✓ Baza ulandi.\n\n⌕ Shu botning <b>yuklash kanali</b> (UPLOAD_CHANNEL_ID) ni yuboring: @username yoki -100... ID.\n"
                     "Bot ham, sizning akkauntingiz ham u yerda admin bo'lishi kerak.", parse_mode="HTML")


@router.message(StateFilter(AddTarget.chan), F.text)
async def add_chan(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    raw = msg.text.strip().replace("https://t.me/", "@")
    d = await state.get_data()
    try:
        from telethon import utils as tl_utils
        ent = await rt.client.get_entity(int(raw) if raw.lstrip("-").isdigit() else raw)
        chat_id = tl_utils.get_peer_id(ent)
    except Exception:
        return await msg.answer("✕ Kanal topilmadi yoki akkaunt a'zo emas. Qayta yuboring.")
    from aiogram import Bot
    bot = Bot(d["bot_token"])
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        if member.status not in ("administrator", "creator"):
            return await msg.answer("✕ Bot bu kanalda admin emas. Admin qiling va qayta yuboring.")
    except Exception:
        return await msg.answer("✕ Bot bu kanalni ko'ra olmayapti (admin qilinganmi?). Qayta yuboring.")
    finally:
        await bot.session.close()
    await state.update_data(upload_channel_id=chat_id, chan_title=getattr(ent, "title", raw))
    await state.set_state(AddTarget.percent)
    await msg.answer(f"✓ Kanal: <b>{html.escape(getattr(ent, 'title', raw))}</b>\n\n% Foiz chegarasini yuboring (1–100). "
                     "Moslik foizi shundan kam bo'lmasa shu botga qo'shiladi. Masalan: 10",
                     parse_mode="HTML")


@router.message(StateFilter(AddTarget.percent), F.text)
async def add_percent(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    pct = _parse_percent(msg.text)
    if pct is None:
        return await msg.answer("✕ 1 dan 100 gacha raqam yuboring.")
    d = await state.get_data()
    cfg = {
        "id": f"yumora-{secrets.token_hex(3)}", "kind": "yumora", "name": d["name"],
        "min_percent": pct, "enabled": True, "bot_username": d["bot_username"],
        "secret": storage.seal({"bot_token": d["bot_token"], "database_url": d["database_url"],
                                "upload_channel_id": d["upload_channel_id"]}),
    }
    items = await _current()
    items.append(cfg)
    await storage.save_targets(items)
    await state.clear()
    await msg.answer(f"{DIV}\n✓ <b>{html.escape(d['name'])}</b> qo'shildi!\n\n@{d['bot_username']} • {pct}%\n"
                     f"Kanal: {html.escape(d['chan_title'])}\n\nEndi yangi postlar avtomatik taqsimlanadi. /targets{chr(10)}{DIV}",
                     parse_mode="HTML")
