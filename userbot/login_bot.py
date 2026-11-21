"""Boshqaruv boti: /start → api_id, api_hash, telefon, kod (nuqtali), [2FA] → kanal, manba bot, tur."""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands,
                           Message)
from telethon import TelegramClient
from telethon.errors import (PasswordHashInvalidError, PhoneCodeExpiredError, PhoneCodeInvalidError,
                             SessionPasswordNeededError)
from telethon.sessions import StringSession

from . import storage
from .runtime import rt

logger = logging.getLogger("userbot")
router = Router()
_pending: dict[int, dict] = {}  # admin_id -> {"client","phone","hash"}

DIV = "✧───────✧"


class Login(StatesGroup):
    api_id = State()
    api_hash = State()
    phone = State()
    code = State()
    password = State()
    channel = State()
    source = State()
    ctype = State()


def _is_admin(uid: int) -> bool:
    return uid == rt.admin_id


async def _wipe(msg: Message) -> None:
    """Maxfiy ma'lumot (hash, kod, parol) chatda qolmasin."""
    try:
        await msg.delete()
    except Exception:
        pass


def _parse_code(text: str) -> str | None:
    singles = re.findall(r"(?<!\d)\d(?!\d)", text)       # 1.2.3.4.5 yoki "user 1.2.3.4.5"
    if len(singles) in (5, 6):
        return "".join(singles)
    m = re.fullmatch(r"\s*(\d{5,6})\s*", text)
    return m.group(1) if m else None


def _panel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [b(text="⌕ Kuzatuv kanallari", callback_data="menu:watch"), b(text="◈ Nishon botlar", callback_data="menu:targets")],
        [b(text="≡ Holat", callback_data="menu:status"), b(text="⊘ Uzish", callback_data="menu:logout")],
    ])


async def setup_menu(bot) -> None:
    """Telegramdagi 'Menu' tugmasi buyruqlar ro'yxatini ko'rsatadi."""
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Panel"),
            BotCommand(command="watch", description="Kuzatuv kanallari (istalgancha)"),
            BotCommand(command="targets", description="Nishon botlar va foizlar"),
            BotCommand(command="status", description="Holat"),
            BotCommand(command="logout", description="Akkauntni uzish"),
            BotCommand(command="cancel", description="Bekor qilish"),
        ])
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception:
        logger.warning("buyruqlar menyusi o'rnatilmadi", exc_info=True)


@router.message(Command("start"))
async def start(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    await state.clear()
    if await storage.load_login():
        return await msg.answer(
            f"{DIV}\n◈ <b>Userbot ulangan.</b>\n\nPastdagi tugmalardan foydalaning yoki buyruqlar menyusini (Menu) oching.\n{DIV}",
            parse_mode="HTML", reply_markup=_panel_kb())
    await state.set_state(Login.api_id)
    await msg.answer(
        f"{DIV}\n◈ <b>Userbot ulash</b>\n\nmy.telegram.org → API development tools dan oling.\n\n№ <b>api_id</b> ni yuboring:\n{DIV}",
        parse_mode="HTML")


@router.message(Command("cancel"))
async def cancel(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    p = _pending.pop(msg.from_user.id, None)
    if p:
        await p["client"].disconnect()
    await state.clear()
    await msg.answer("✕ Bekor qilindi. /start")


@router.message(StateFilter(Login.api_id), F.text)
async def got_api_id(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    if not msg.text.strip().isdigit():
        return await msg.answer("✕ Faqat raqam yuboring.")
    await state.update_data(api_id=int(msg.text.strip()))
    await state.set_state(Login.api_hash)
    await msg.answer("# <b>api_hash</b> ni yuboring (xabar o'chiriladi):", parse_mode="HTML")


@router.message(StateFilter(Login.api_hash), F.text)
async def got_api_hash(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    h = msg.text.strip()
    await _wipe(msg)
    if not re.fullmatch(r"[0-9a-fA-F]{32}", h):
        return await msg.answer("✕ api_hash 32 belgili bo'lishi kerak. Qayta yuboring.")
    await state.update_data(api_hash=h)
    await state.set_state(Login.phone)
    await msg.answer("☎ <b>Telefon raqam</b>ni yuboring (+998...):", parse_mode="HTML")


@router.message(StateFilter(Login.phone), F.text)
async def got_phone(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    phone = msg.text.strip().replace(" ", "")
    d = await state.get_data()
    client = TelegramClient(StringSession(), d["api_id"], d["api_hash"])
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
    except Exception as e:
        await client.disconnect()
        return await msg.answer(f"✕ Kod yuborilmadi: {type(e).__name__}\nRaqamni qayta yuboring yoki /cancel")
    _pending[msg.from_user.id] = {"client": client, "phone": phone, "hash": sent.phone_code_hash}
    await state.set_state(Login.code)
    await msg.answer(
        f"{DIV}\n✓ Kod Telegram akkauntingizga yuborildi.\n\n"
        "Telegram kodni xabarda ochiq yuborsangiz bekor qiladi. Shuning uchun <b>har bir raqamdan keyin nuqta</b> bilan yuboring:\n\n"
        "Kod <code>12345</code> bo'lsa → <code>1.2.3.4.5</code>\n"
        f"{DIV}", parse_mode="HTML")


@router.message(StateFilter(Login.code), F.text)
async def got_code(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    code = _parse_code(msg.text)
    await _wipe(msg)
    if not code:
        return await msg.answer("✕ Kod formati noto'g'ri. Masalan: <code>1.2.3.4.5</code>", parse_mode="HTML")
    p = _pending.get(msg.from_user.id)
    if not p:
        return await msg.answer("✕ Seans topilmadi. /start")
    try:
        await p["client"].sign_in(phone=p["phone"], code=code, phone_code_hash=p["hash"])
    except SessionPasswordNeededError:
        await state.set_state(Login.password)
        return await msg.answer("⊘ 2 bosqichli parol yoqilgan. <b>Parolni</b> yuboring (xabar o'chiriladi):", parse_mode="HTML")
    except PhoneCodeInvalidError:
        return await msg.answer("✕ Kod noto'g'ri. Qayta yuboring.")
    except PhoneCodeExpiredError:
        sent = await p["client"].send_code_request(p["phone"])
        p["hash"] = sent.phone_code_hash
        return await msg.answer("✕ Kod eskirdi, yangisi yuborildi. Uni nuqtali yuboring.")
    await _finish_login(msg, state)


@router.message(StateFilter(Login.password), F.text)
async def got_password(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    pw = msg.text
    await _wipe(msg)
    p = _pending.get(msg.from_user.id)
    try:
        await p["client"].sign_in(password=pw)
    except PasswordHashInvalidError:
        return await msg.answer("✕ Parol noto'g'ri. Qayta yuboring.")
    await _finish_login(msg, state)


async def _finish_login(msg: Message, state: FSMContext):
    p = _pending.pop(msg.from_user.id)
    d = await state.get_data()
    client = p["client"]
    await storage.save_login(d["api_id"], d["api_hash"], client.session.save())
    rt.client = client
    await state.set_state(Login.channel)
    await msg.answer(f"{DIV}\n✓ <b>Akkaunt ulandi!</b>\n\n⌕ Kuzatiladigan <b>kanal username</b>ini yuboring (masalan @kanal_nomi).\nAkkauntingiz shu kanalga obuna bo'lgan bo'lishi kerak.\n{DIV}", parse_mode="HTML")


@router.message(StateFilter(Login.channel), F.text)
async def got_channel(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    ch = msg.text.strip().replace("https://t.me/", "@")
    try:
        ent = await rt.client.get_entity(ch)
    except Exception:
        return await msg.answer("✕ Kanal topilmadi yoki akkaunt obuna emas. Qayta yuboring.")
    await state.update_data(channel=ent.id, channel_title=getattr(ent, "title", ch))
    await state.set_state(Login.source)
    await msg.answer(f"✓ Kanal: <b>{getattr(ent, 'title', ch)}</b>\n\n▣ Endi qismlarni oladigan <b>manba bot username</b>ini yuboring (@bot):", parse_mode="HTML")


@router.message(StateFilter(Login.source), F.text)
async def got_source(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    b = msg.text.strip().replace("https://t.me/", "@")
    try:
        await rt.client.get_entity(b)
    except Exception:
        return await msg.answer("✕ Bot topilmadi. Qayta yuboring.")
    await state.update_data(source_bot=b)
    await state.set_state(Login.ctype)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ᐅ Anime", callback_data="ubt:anime"), InlineKeyboardButton(text="ᐅ Dorama", callback_data="ubt:dorama")],
        [InlineKeyboardButton(text="ᐅ Serial", callback_data="ubt:serial"), InlineKeyboardButton(text="ᐅ Kino", callback_data="ubt:movie")],
    ])
    await msg.answer("≡ Bu kanaldagi kontent <b>turi</b>:", parse_mode="HTML", reply_markup=kb)


@router.callback_query(StateFilter(Login.ctype), F.data.startswith("ubt:"))
async def got_type(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    d = await state.get_data()
    cfg = {"channel": d["channel"], "source_bot": d["source_bot"], "content_type": call.data.split(":")[1],
           "title": d["channel_title"]}
    items = [w for w in await storage.load_watches() if w["channel"] != cfg["channel"]]   # shu kanal bo'lsa — yangilanadi
    items.append(cfg)
    await storage.save_watches(items)
    await state.clear()
    from .watcher import start_watcher
    await start_watcher()
    await call.message.answer(f"{DIV}\n✓ <b>Kuzatuv boshlandi!</b>\n\n⌕ Kanal: {d['channel_title']}\n▣ Manba: {d['source_bot']}\n≡ Tur: {cfg['content_type']}\n\nJami kuzatuv kanallari: {len(items)}. Yana qo'shish: /watch\nYangi post chiqsa, men sizga yozaman.\n{DIV}", parse_mode="HTML")
    await call.answer()


async def _watch_view() -> tuple[str, InlineKeyboardMarkup]:
    items = await storage.load_watches()
    lines = [f"{DIV}\n◈ <b>Kuzatiladigan kanallar</b>: {len(items)} ta\n"]
    kb = []
    for i, w in enumerate(items, 1):
        title = html.escape(w.get("title") or str(w["channel"]))
        lines.append(f"{i}. <b>{title}</b> — {html.escape(w['source_bot'])} • {w['content_type']}")
        kb.append([InlineKeyboardButton(text=f"✕ {w.get('title') or w['channel']}", callback_data=f"wc:del:{w['channel']}")])
    if not items:
        lines.append("Hozircha kanal yo'q.")
    lines.append(f"\nIstalgancha kanal qo'shishingiz mumkin. Har biri o'z manba boti va turi bilan.\n{DIV}")
    kb.append([InlineKeyboardButton(text="＋ Kanal qo'shish", callback_data="wc:add")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


@router.message(Command("watch"))
async def watch_cmd(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    if not rt.client:
        return await msg.answer("✕ Avval /start bilan akkauntni ulang.")
    await state.clear()
    text, kb = await _watch_view()
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "wc:add")
async def watch_add(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    if not rt.client:
        return await call.answer("Avval /start bilan akkauntni ulang.", show_alert=True)
    await state.set_state(Login.channel)
    await call.message.answer("⌕ Yangi kanal usernameini yuboring (bekor qilish: /cancel):")
    await call.answer()


@router.callback_query(F.data.startswith("wc:del:"))
async def watch_del(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    cid = int(call.data.split(":", 2)[2])
    await storage.save_watches([w for w in await storage.load_watches() if w["channel"] != cid])
    from .watcher import start_watcher
    await start_watcher()
    text, kb = await _watch_view()
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await call.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await call.answer("✓ Olib tashlandi")


def _ago(ts: float) -> str:
    d = int(time.time() - ts)
    return f"{d} soniya oldin" if d < 90 else f"{d // 60} daqiqa oldin" if d < 5400 else f"{d // 3600} soat oldin"


async def _status_text() -> str:
    items = await storage.load_watches()
    c = rt.client
    connected = bool(c and c.is_connected())
    authorized = None
    if connected:
        try:
            authorized = bool(await asyncio.wait_for(c.is_user_authorized(), 10))
        except Exception:
            authorized = None
    tg = ("✓ ulangan" if authorized else "✕ sessiya BEKOR qilingan (/logout, /start)" if authorized is False else "? tekshirib bo'lmadi") \
        if connected else "✕ ULANMAGAN"
    rows = []
    for w in items:
        seen = rt.last_seen.get(w["channel"])
        rows.append(f"• {html.escape(w.get('title') or str(w['channel']))} — {html.escape(w['source_bot'])} • {w['content_type']}\n"
                    f"   oxirgi post: {_ago(seen) if seen else 'ishga tushgandan beri kelmagan'}")
    work = f"{html.escape(rt.current)} ({int(time.time() - rt.current_since)}s)" if rt.current else "—"
    up = _ago(rt.started_at).replace(" oldin", "") if rt.started_at else "—"
    return (f"◈ Userbot: {'✓ ishlayapti' if connected else '✕ o‘chiq'}\n≡ Telegram: {tg}\n"
            f"⌕ Kuzatuv kanallari ({len(items)}):\n" + ("\n".join(rows) or "—")
            + f"\n◌ Navbatda: {rt.queue.qsize()} • hozir: {work}\n⏱ Ishlayapti: {up}")


@router.message(Command("status"))
async def status(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    await msg.answer(await _status_text(), parse_mode="HTML")


async def _do_logout(state: FSMContext) -> None:
    if rt.client:
        try:
            await rt.client.log_out()
        except Exception:
            pass
        rt.client = None
    await storage.clear_login()
    await state.clear()


@router.message(Command("logout"))
async def logout(msg: Message, state: FSMContext):
    if not _is_admin(msg.from_user.id):
        return
    await _do_logout(state)
    await msg.answer("✓ Uzildi, sessiya o'chirildi. /start")


@router.callback_query(F.data.startswith("menu:"))
async def menu_cb(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    action = call.data.split(":", 1)[1]
    if action == "watch":
        if not rt.client:
            return await call.answer("Avval /start bilan akkauntni ulang.", show_alert=True)
        text, kb = await _watch_view()
        await call.message.answer(text, parse_mode="HTML", reply_markup=kb)
    elif action == "targets":
        from .targets_bot import _list_view
        text, kb = await _list_view()
        await call.message.answer(text, parse_mode="HTML", reply_markup=kb)
    elif action == "status":
        await call.message.answer(await _status_text(), parse_mode="HTML")
    elif action == "logout":
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✓ Ha, uzish", callback_data="menu:logout_yes"),
            InlineKeyboardButton(text="✕ Yo'q", callback_data="menu:cancel")]])
        await call.message.answer("⊘ Akkaunt uziladi va sessiya o'chiriladi. Rostdan uzasizmi?", reply_markup=kb)
    elif action == "logout_yes":
        await _do_logout(state)
        await call.message.answer("✓ Uzildi, sessiya o'chirildi. /start")
    elif action == "cancel":
        pass
    if action in ("logout_yes", "cancel"):
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await call.answer()


@router.callback_query(F.data.regexp(r"^ub_(ok|retry|cancel):"))
async def confirm_cb(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        return await call.answer()
    action, job = call.data[3:].split(":")
    fut = rt.confirms.get(job)
    if fut and not fut.done():
        fut.set_result(action)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.answer()


@router.message(F.text & ~F.text.startswith("/"))
async def free_text(msg: Message):
    """Pipeline savol bergan bo'lsa (inglizcha nom) — javobni shu yerda olamiz."""
    if _is_admin(msg.from_user.id) and rt.text_waiter and not rt.text_waiter.done():
        rt.text_waiter.set_result(msg.text.strip())
