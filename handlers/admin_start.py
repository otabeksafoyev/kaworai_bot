"""
handlers/admin_start.py — admin: /start rasmi va /start tugmalarini boshqarish.

Admin panel → "✦ Start sozlash":
  ▣ Rasmni almashtirish / ↻ Standart rasmga qaytarish
  + Tugma qo'shish: nom → kim uchun (hamma/Pro/oddiy) → tur:
        ↗ Link  — bosilganda havola o'zi ochiladi
        ✎ Javob — bosilganda bot matn yuboradi, javobga istalgancha link-tugma qo'shiladi
  ≡ Tugmalar — ro'yxat va o'chirish
Foydalanuvchi tomoni: `sbtn_<id>` callback (faqat "Javob" turi).
Ruxsat: egasi (owner) va "start_cfg" ruxsati berilgan adminlar.
"""

from __future__ import annotations

import html
import logging
import re

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Markup

from handlers.admin import has_permission, is_admin, is_partner_user
from states.admin_states import StartCfg
from utils.start_cfg import (
    AUDIENCES,
    add_button,
    audience_ok,
    delete_button,
    get_button,
    get_start_photo,
    is_pro_user,
    load_buttons,
    set_start_photo,
)
from utils.ui import sym

logger = logging.getLogger(__name__)
start_admin_router = Router()

_URL_RE = re.compile(r"^(https?://|tg://)\S+$", re.IGNORECASE)


def _norm_url(raw: str) -> str | None:
    raw = (raw or "").strip()
    if raw.startswith("@") and len(raw) > 1:
        raw = f"https://t.me/{raw[1:]}"
    elif raw.lower().startswith(("t.me/", "telegram.me/")):
        raw = "https://" + raw
    return raw if _URL_RE.match(raw) else None


async def _allowed(user_id: int) -> bool:
    if not await is_admin(user_id) or await is_partner_user(user_id):
        return False
    return await has_permission(user_id, "start_cfg")


def _back_kb() -> Markup:
    return Markup(inline_keyboard=[[Btn(text="ᐊ Orqaga", callback_data="scfg_menu")]])


async def _show_menu(target: types.Message | types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    has_photo = bool(await get_start_photo())
    n = len(await load_buttons())
    text = (
        "✦ <b>Start sozlash</b>\n✧───────✧\n"
        f"▣ Rasm: <b>{'o‘zgartirilgan' if has_photo else 'standart'}</b>\n"
        f"≡ Qo'shilgan tugmalar: <b>{n}</b>"
    )
    rows = [[Btn(text="▣ Rasmni almashtirish", callback_data="scfg_photo")]]
    if has_photo:
        rows.append([Btn(text="↻ Standart rasmga qaytarish", callback_data="scfg_photo_reset")])
    rows.append([Btn(text="+ Tugma qo'shish", callback_data="scfg_add"), Btn(text="≡ Tugmalar", callback_data="scfg_list")])
    rows.append([Btn(text="✕ Yopish", callback_data="scfg_close")])
    kb = Markup(inline_keyboard=rows)
    if isinstance(target, types.CallbackQuery):
        try:
            return await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            target = target.message
    await target.answer(text, reply_markup=kb, parse_mode="HTML")


async def _show_list(call: types.CallbackQuery) -> None:
    buttons = await load_buttons()
    if not buttons:
        text = "≡ <b>Tugmalar</b>\n\nHali tugma qo'shilmagan."
    else:
        lines = []
        for i, b in enumerate(buttons, 1):
            kind = f"↗ {html.escape(b.get('url', ''))}" if b.get("kind") == "link" else f"✎ javob ({len(b.get('links') or [])} link)"
            lines.append(f"{i}. <b>{html.escape(b['label'])}</b> · {AUDIENCES.get(b.get('audience', 'all'))}\n    {kind}")
        text = "≡ <b>Tugmalar</b>\n\n" + "\n".join(lines)
    rows = [[Btn(text=f"✕ {sym(b['label'])}", callback_data=f"scfg_del_{b['id']}")] for b in buttons]
    rows.append([Btn(text="ᐊ Orqaga", callback_data="scfg_menu")])
    try:
        await call.message.edit_text(
            text, reply_markup=Markup(inline_keyboard=rows), parse_mode="HTML", disable_web_page_preview=True
        )
    except Exception:
        pass


# ─── Kirish ───────────────────────────────────────────────────────────
@start_admin_router.message(F.text == "✦ Start sozlash")
async def start_cfg_entry(msg: types.Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if not await _allowed(msg.from_user.id):
        return await msg.answer("✕ Sizda bu bo'limga ruxsat yo'q. Asosiy admin bilan bog'laning.")
    await _show_menu(msg, state)


# ─── Navigatsiya (barcha scfg_* callbacklar shu yerda, ruxsat bilan) ───
@start_admin_router.callback_query(F.data.startswith("scfg_"))
async def start_cfg_callbacks(call: types.CallbackQuery, state: FSMContext):
    if not await _allowed(call.from_user.id):
        return await call.answer("✕ Ruxsat yo'q", show_alert=True)
    await call.answer()
    data = call.data

    if data == "scfg_menu":
        return await _show_menu(call, state)
    if data == "scfg_close":
        await state.clear()
        try:
            await call.message.delete()
        except Exception:
            pass
        return
    if data == "scfg_photo":
        await state.set_state(StartCfg.photo)
        return await call.message.edit_text(
            "▣ <b>Yangi /start rasmi</b>\n\nRasmni oddiy <b>rasm</b> sifatida yuboring (fayl emas).",
            reply_markup=_back_kb(),
            parse_mode="HTML",
        )
    if data == "scfg_photo_reset":
        await set_start_photo(None)
        return await _show_menu(call, state)
    if data == "scfg_add":
        await state.clear()
        await state.set_state(StartCfg.label)
        return await call.message.edit_text(
            "+ <b>Yangi tugma</b>\n\nTugma <b>nomini</b> yozing (masalan: <i>Pro haqida</i>).",
            reply_markup=_back_kb(),
            parse_mode="HTML",
        )
    if data == "scfg_list":
        return await _show_list(call)
    if data.startswith("scfg_del_"):
        await delete_button(data.replace("scfg_del_", "", 1))
        return await _show_list(call)

    if data.startswith("scfg_aud_"):
        aud = data.replace("scfg_aud_", "", 1)
        if aud not in AUDIENCES or (await state.get_state()) != StartCfg.label.state:
            return
        await state.update_data(audience=aud)
        kb = Markup(
            inline_keyboard=[
                [Btn(text="↗ Link — bosilsa havola ochiladi", callback_data="scfg_kind_link")],
                [Btn(text="✎ Javob — bosilsa bot xabar yozadi", callback_data="scfg_kind_reply")],
                [Btn(text="ᐊ Orqaga", callback_data="scfg_menu")],
            ]
        )
        return await call.message.edit_text(
            f"Ko'rinadi: <b>{AUDIENCES[aud]}</b>\n\nTugma bosilganda nima bo'lsin?", reply_markup=kb, parse_mode="HTML"
        )

    if data.startswith("scfg_kind_"):
        d = await state.get_data()
        if not d.get("label") or not d.get("audience"):
            return
        if data.endswith("link"):
            await state.update_data(kind="link")
            await state.set_state(StartCfg.url)
            text = "↗ Havolani yuboring (<code>https://…</code>, <code>t.me/…</code> yoki <code>@username</code>)."
        else:
            await state.update_data(kind="reply", links=[])
            await state.set_state(StartCfg.text)
            text = "✎ Tugma bosilganda bot yozadigan <b>matnni</b> yuboring (qalin/kursiv formatlash saqlanadi)."
        return await call.message.edit_text(text, reply_markup=_back_kb(), parse_mode="HTML")

    if data == "scfg_links_done":
        d = await state.get_data()
        if d.get("kind") != "reply" or not d.get("text"):
            return
        await add_button(
            {"label": d["label"], "audience": d["audience"], "kind": "reply", "text": d["text"], "links": d.get("links", [])}
        )
        await state.clear()
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer("✓ Tugma /start ga qo'shildi.")
        return await _show_menu(call.message, state)


# ─── Rasm ─────────────────────────────────────────────────────────────
@start_admin_router.message(StartCfg.photo, F.photo)
async def start_cfg_photo(msg: types.Message, state: FSMContext):
    if not await _allowed(msg.from_user.id):
        return
    file_id = msg.photo[-1].file_id
    await set_start_photo(file_id)
    try:
        await msg.answer_photo(photo=file_id, caption="✓ <b>Yangi /start rasmi saqlandi</b>", parse_mode="HTML")
    except Exception:
        await msg.answer("✓ Saqlandi")
    await _show_menu(msg, state)


@start_admin_router.message(StartCfg.photo)
async def start_cfg_photo_bad(msg: types.Message):
    await msg.answer("✕ Rasm yuboring (fayl emas, oddiy rasm).", reply_markup=_back_kb())


# ─── Tugma nomi ───────────────────────────────────────────────────────
@start_admin_router.message(StartCfg.label, F.text)
async def start_cfg_label(msg: types.Message, state: FSMContext):
    if not await _allowed(msg.from_user.id):
        return
    label = (msg.text or "").strip()
    if not label or len(label) > 40:
        return await msg.answer("✕ Nom 1–40 belgi bo'lsin.", reply_markup=_back_kb())
    await state.update_data(label=label)
    kb = Markup(
        inline_keyboard=[
            [Btn(text="◉ Hamma uchun", callback_data="scfg_aud_all")],
            [Btn(text="◆ Faqat Pro uchun", callback_data="scfg_aud_pro")],
            [Btn(text="○ Faqat oddiy user uchun", callback_data="scfg_aud_user")],
            [Btn(text="ᐊ Orqaga", callback_data="scfg_menu")],
        ]
    )
    await msg.answer(f"Tugma: <b>{html.escape(label)}</b>\n\nU <b>kimga</b> ko'rinsin?", reply_markup=kb, parse_mode="HTML")


# ─── Link turi ────────────────────────────────────────────────────────
@start_admin_router.message(StartCfg.url, F.text)
async def start_cfg_url(msg: types.Message, state: FSMContext):
    if not await _allowed(msg.from_user.id):
        return
    url = _norm_url(msg.text)
    if not url:
        return await msg.answer("✕ Havola noto'g'ri. Masalan: <code>https://t.me/kanal</code>", parse_mode="HTML")
    d = await state.get_data()
    await add_button({"label": d["label"], "audience": d["audience"], "kind": "link", "url": url})
    await msg.answer("✓ Tugma /start ga qo'shildi — bosilganda havola o'zi ochiladi.")
    await _show_menu(msg, state)


# ─── Javob turi: matn → link-tugmalar (cheksiz) ───────────────────────
def _links_kb(count: int) -> Markup:
    done = "✓ Tayyor, saqlash" if count else "✓ Tugmasiz saqlash"
    return Markup(inline_keyboard=[[Btn(text=done, callback_data="scfg_links_done")]])


@start_admin_router.message(StartCfg.text, F.text)
async def start_cfg_text(msg: types.Message, state: FSMContext):
    if not await _allowed(msg.from_user.id):
        return
    await state.update_data(text=msg.html_text, links=[])
    await state.set_state(StartCfg.link_label)
    await msg.answer(
        "+ <b>Javobga tugma</b> (hozir: 0 ta)\n\nTugma <b>nomini</b> yozing yoki pastdagi tugmani bosing.",
        reply_markup=_links_kb(0),
        parse_mode="HTML",
    )


@start_admin_router.message(StartCfg.link_label, F.text)
async def start_cfg_link_label(msg: types.Message, state: FSMContext):
    if not await _allowed(msg.from_user.id):
        return
    label = (msg.text or "").strip()
    if not label or len(label) > 40:
        return await msg.answer("✕ Nom 1–40 belgi bo'lsin.")
    await state.update_data(link_label=label)
    await state.set_state(StartCfg.link_url)
    await msg.answer(f"↗ <b>{html.escape(label)}</b> uchun havolani yuboring.", parse_mode="HTML")


@start_admin_router.message(StartCfg.link_url, F.text)
async def start_cfg_link_url(msg: types.Message, state: FSMContext):
    if not await _allowed(msg.from_user.id):
        return
    url = _norm_url(msg.text)
    if not url:
        return await msg.answer("✕ Havola noto'g'ri. Masalan: <code>https://t.me/kanal</code>", parse_mode="HTML")
    d = await state.get_data()
    links = list(d.get("links") or []) + [{"label": d["link_label"], "url": url}]
    await state.update_data(links=links)
    await state.set_state(StartCfg.link_label)
    await msg.answer(
        f"✓ Qo'shildi. Hozir: <b>{len(links)}</b> ta tugma.\n\nYana tugma nomini yozing yoki saqlang.",
        reply_markup=_links_kb(len(links)),
        parse_mode="HTML",
    )


# ─── Foydalanuvchi: "Javob" turidagi tugma bosildi ────────────────────
@start_admin_router.callback_query(F.data.startswith("sbtn_"))
async def start_button_pressed(call: types.CallbackQuery):
    btn = await get_button(call.data.replace("sbtn_", "", 1))
    if not btn or btn.get("kind") != "reply":
        return await call.answer("Bu tugma endi mavjud emas", show_alert=True)
    if not audience_ok(btn, await is_pro_user(call.from_user.id)):
        return await call.answer("Bu tugma siz uchun emas", show_alert=True)
    await call.answer()
    rows = [[Btn(text=sym(l["label"]), url=l["url"])] for l in btn.get("links") or []]
    rows.append([Btn(text="ᐊ Menyu", callback_data="main_menu")])
    try:
        await call.message.answer(
            btn.get("text") or "—",
            reply_markup=Markup(inline_keyboard=rows),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.warning("sbtn javobini yuborib bo'lmadi: %s", btn.get("id"), exc_info=True)
