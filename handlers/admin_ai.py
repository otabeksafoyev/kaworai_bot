"""
handlers/admin_ai.py — "➕ Kontent qo'shish" da AI rejimi.

Oqim:
  ➕ Kontent qo'shish → [🤖 AI bilan] / [✍️ Qo'lda]
  AI: ID → poster → treyler → nom → inglizcha nom → AI ma'lumot yig'adi
      → ko'rib chiqish: ✅ To'g'ri (saqlanadi + kanalga post so'raladi)
                         🔄 AI qaytadan / ✍️ Qo'lda davom etish / 🚫 Bekor
"""

from __future__ import annotations

import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from data import config
from database.engine import AsyncSessionLocal
from database.models import Anime
from handlers.admin import (
    TYPE_KB,
    _get_telegram_file_url,
    _poster_rejection_reason,
    _save_anime,
    _skip_kb,
    _strip_season_suffix,
    _trailer_rejection_reason,
    admin_main_kb,
    cancel_kb,
    is_admin,
)
from handlers.genres import GENRES
from states.admin_states import AddAnime, AddAnimeAI
from utils.ai_anime import build_content_info
from utils.security import esc
from utils.ui import sym

logger = logging.getLogger(__name__)
ai_admin_router = Router()

CANCEL_TEXT = "🚫 Bekor qilish"
TYPE_LABEL = {"anime": "🎌 Anime", "movie": "🎥 Kino", "serial": "📺 Serial", "dorama": "🌸 Dorama"}
STATUS_LABEL = {"ongoing": "📡 Davom etmoqda", "completed": "✅ Tugagan", "announced": "📢 Kutilmoqda"}


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✓ To'g'ri, saqlash", callback_data="aiadd_ok")],
            [InlineKeyboardButton(text="✎ Tahrirlash", callback_data="aiadd_edit")],
            [
                InlineKeyboardButton(text="↻ AI qaytadan", callback_data="aiadd_retry"),
                InlineKeyboardButton(text="✎ Noldan qo'lda", callback_data="aiadd_manual"),
            ],
            [InlineKeyboardButton(text="✕ Bekor qilish", callback_data="aiadd_cancel")],
        ]
    )


async def _cancel(msg: Message, state: FSMContext) -> None:
    await state.clear()
    await msg.answer("Bekor.", reply_markup=admin_main_kb)


# ─── Rejim tanlash ────────────────────────────────────────────────────

@ai_admin_router.callback_query(F.data == "addmode_manual")
async def mode_manual(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    await state.set_state(AddAnime.waiting_id)
    await call.message.answer(
        "✍️ <b>Qo'lda qo'shish</b>\n\n"
        "Qadamlar: ID → Nom → Tur → Tavsif → Rasm → Holat\n\n"
        "🆔 <b>Kontent ID</b>sini kiriting (faqat raqam):\n<i>Masalan: <code>4345</code></i>",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )
    await call.answer()


@ai_admin_router.callback_query(F.data == "addmode_ai")
async def mode_ai(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    await state.clear()
    await state.set_state(AddAnimeAI.waiting_id)
    await call.message.answer(
        "🤖 <b>AI bilan qo'shish</b>\n\n"
        "Qadamlar: ID → Poster → Treyler → Nom → Inglizcha nom\n"
        "Qolganini (tur, tavsif, janr, yil, reyting, qismlar...) AI to'ldiradi.\n\n"
        "🆔 <b>Kontent ID</b>sini kiriting (faqat raqam):",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )
    await call.answer()


# ─── 1) ID ────────────────────────────────────────────────────────────

@ai_admin_router.message(AddAnimeAI.waiting_id)
async def ai_get_id(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == CANCEL_TEXT:
        return await _cancel(msg, state)
    if not (msg.text or "").isdigit():
        return await msg.answer("❌ Faqat raqam!")
    anime_id = int(msg.text)
    async with AsyncSessionLocal() as session:
        if await session.get(Anime, anime_id):
            sug = ((await session.execute(select(func.max(Anime.id)))).scalar() or 0) + 1
            return await msg.answer(f"❌ ID {anime_id} mavjud!\n💡 Bo'sh ID: <code>{sug}</code>", parse_mode="HTML")
    await state.update_data(anime_id=anime_id)
    await state.set_state(AddAnimeAI.waiting_poster)
    await msg.answer(
        "🖼 <b>Poster rasmini yuboring:</b>",
        parse_mode="HTML",
        reply_markup=_skip_kb("aiadd_skip_poster"),
    )


# ─── 2) Poster ────────────────────────────────────────────────────────

async def _ask_trailer(target: Message) -> None:
    await target.answer(
        "🎬 <b>Treyler videosini yuboring:</b>",
        parse_mode="HTML",
        reply_markup=_skip_kb("aiadd_skip_trailer"),
    )


@ai_admin_router.callback_query(F.data == "aiadd_skip_poster", AddAnimeAI.waiting_poster)
async def ai_skip_poster(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(poster_file_id=None, inline_thumbnail_url=None)
    await state.set_state(AddAnimeAI.waiting_trailer)
    await _ask_trailer(call.message)
    await call.answer()


async def _photo_to_url(bot, photo: types.PhotoSize, name: str) -> str | None:
    """Rasmni ImgBB ga yuklab doimiy URL oladi; bo'lmasa Telegram CDN URL."""
    url = None
    try:
        from utils.imgbb import upload_telegram_photo_to_imgbb

        if getattr(config, "IMGBB_API_KEY", ""):
            url = await upload_telegram_photo_to_imgbb(bot, photo.file_id, config.IMGBB_API_KEY, name=name)
    except Exception:
        logger.warning("ImgBB xato", exc_info=True)
    return url or await _get_telegram_file_url(bot, photo.file_id)


@ai_admin_router.message(AddAnimeAI.waiting_poster, F.photo)
async def ai_get_poster(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    photo = msg.photo[-1]
    rejection = _poster_rejection_reason(photo)
    if rejection:
        return await msg.answer(rejection + "\nIltimos, kichikroq rasm yuboring.")

    w, h = photo.width, photo.height
    ratio = w / h if h else 1.0
    anime_id = (await state.get_data())["anime_id"]
    await state.update_data(poster_file_id=photo.file_id, inline_thumbnail_url=None)

    if ratio <= 1.05:  # portret/kvadrat — inline qidiruv uchun yaroqli, avtomatik URL
        wait = await msg.answer("⏳ Rasm URL'ga aylantirilmoqda...")
        url = await _photo_to_url(msg.bot, photo, f"poster_{anime_id}")
        try:
            await wait.delete()
        except Exception:
            pass
        if url:
            await state.update_data(inline_thumbnail_url=url)
            await state.set_state(AddAnimeAI.waiting_trailer)
            return await _ask_trailer(msg)

    # Landscape (yoki URL olinmadi) — inline qidiruv uchun alohida rasm/URL so'raymiz
    await state.set_state(AddAnimeAI.waiting_inline)
    await msg.answer(
        f"⚠️ <b>Landscape rasm</b> ({w}×{h}) — kanalga poster sifatida saqlandi, "
        "lekin inline qidiruvda xunuk ko'rinadi 😕\n\n"
        "Inline qidiruv uchun <b>kvadrat yoki portret rasm</b> yuboring "
        "(men o'zim URL qilaman) yoki <b>rasm URL</b>sini (https://...) yuboring.",
        parse_mode="HTML",
        reply_markup=_skip_kb("aiadd_skip_inline"),
    )


@ai_admin_router.callback_query(F.data == "aiadd_skip_inline", AddAnimeAI.waiting_inline)
async def ai_skip_inline(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddAnimeAI.waiting_trailer)
    await _ask_trailer(call.message)
    await call.answer()


@ai_admin_router.message(AddAnimeAI.waiting_inline, F.photo)
async def ai_get_inline_photo(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    photo = msg.photo[-1]
    if photo.height and photo.width / photo.height > 1.05:
        return await msg.answer("❌ Bu rasm ham keng. Kvadrat yoki portret rasm yuboring (yoki URL).")
    anime_id = (await state.get_data())["anime_id"]
    url = await _photo_to_url(msg.bot, photo, f"inline_{anime_id}")
    if not url:
        return await msg.answer("❌ Rasmdan URL olinmadi. URL yuboring yoki o'tkazib yuboring.")
    await state.update_data(inline_thumbnail_url=url)
    await state.set_state(AddAnimeAI.waiting_trailer)
    await msg.answer("✅ Inline rasm qabul qilindi.")
    await _ask_trailer(msg)


@ai_admin_router.message(AddAnimeAI.waiting_inline, F.text)
async def ai_get_inline_url(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == CANCEL_TEXT:
        return await _cancel(msg, state)
    url = msg.text.strip()
    if not url.startswith("http"):
        return await msg.answer("❌ Rasm yuboring yoki https:// bilan boshlanadigan URL yozing.")
    await state.update_data(inline_thumbnail_url=url)
    await state.set_state(AddAnimeAI.waiting_trailer)
    await msg.answer("✅ Inline URL qabul qilindi.")
    await _ask_trailer(msg)


# Qo'lda oqimda ham: landscape bo'lsa URL o'rniga rasm yuborish mumkin
@ai_admin_router.message(F.photo, AddAnime.waiting_inline_url)
async def manual_inline_photo(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    photo = msg.photo[-1]
    if photo.height and photo.width / photo.height > 1.05:
        return await msg.answer("❌ Bu rasm ham keng. Kvadrat yoki portret rasm yuboring (yoki URL).")
    anime_id = (await state.get_data()).get("anime_id", "x")
    url = await _photo_to_url(msg.bot, photo, f"inline_{anime_id}")
    if not url:
        return await msg.answer("❌ Rasmdan URL olinmadi. URL yuboring.")
    await state.update_data(inline_thumbnail_url=url)
    await state.set_state(AddAnime.waiting_trailer)
    await msg.answer("✅ Inline rasm qabul qilindi.\n\n🎬 <b>Treyler videosini yuboring:</b>",
                     parse_mode="HTML", reply_markup=_skip_kb("skip_trailer"))


@ai_admin_router.message(AddAnimeAI.waiting_poster)
async def ai_poster_other(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == CANCEL_TEXT:
        return await _cancel(msg, state)
    await msg.answer("❌ Rasm yuboring (yoki «O'tkazib yuborish» ni bosing).")


# ─── 3) Treyler ───────────────────────────────────────────────────────

async def _ask_title(target: Message) -> None:
    await target.answer(
        "📝 <b>Nomini yuboring:</b>\n<i>Botda ko'rinadigan nom. Masalan: Attack on Titan</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )


@ai_admin_router.callback_query(F.data == "aiadd_skip_trailer", AddAnimeAI.waiting_trailer)
async def ai_skip_trailer(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(trailer_file_id=None)
    await state.set_state(AddAnimeAI.waiting_title)
    await _ask_title(call.message)
    await call.answer()


@ai_admin_router.message(AddAnimeAI.waiting_trailer, F.video)
async def ai_get_trailer(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    rejection = _trailer_rejection_reason(msg.video)
    if rejection:
        return await msg.answer(rejection + "\nIltimos, qisqaroq/kichikroq video yuboring.")
    await state.update_data(trailer_file_id=msg.video.file_id)
    await state.set_state(AddAnimeAI.waiting_title)
    await _ask_title(msg)


@ai_admin_router.message(AddAnimeAI.waiting_trailer)
async def ai_trailer_other(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == CANCEL_TEXT:
        return await _cancel(msg, state)
    await msg.answer("❌ Video yuboring (yoki «O'tkazib yuborish» ni bosing).")


# ─── 4) Nom ───────────────────────────────────────────────────────────

@ai_admin_router.message(AddAnimeAI.waiting_title, F.text)
async def ai_get_title(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == CANCEL_TEXT:
        return await _cancel(msg, state)
    title = msg.text.strip()
    if not title:
        return await msg.answer("❌ Nom bo'sh bo'la olmaydi.")
    await state.update_data(title=title)
    await state.set_state(AddAnimeAI.waiting_english)
    await msg.answer(
        "🔎 <b>Inglizcha nomini yuboring</b> (AI topa olishi uchun):\n"
        "<i>Masalan: Jujutsu Kaisen, Fullmetal Alchemist: Brotherhood</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )


# ─── 5) Inglizcha nom → AI ────────────────────────────────────────────

def _preview_text(d: dict) -> str:
    genres = ", ".join(GENRES.get(g, g) for g in d.get("genres") or []) or "—"
    tags = ", ".join(d.get("tags") or []) or "—"
    mood = ", ".join(d.get("mood") or []) or "—"
    desc = d.get("desc") or "—"
    if len(desc) > 600:
        desc = desc[:600] + "…"
    src = " + ".join(d.get("sources") or []) or "hech narsa topilmadi"
    matched = d.get("matched_title")
    note = d.get("note")
    lines = [
        f"🤖 <b>AI natijasi</b>  <i>({esc(src)})</i>",
        f"🔗 Topilgan nom: <b>{esc(matched)}</b>" if matched else "⚠️ MyAnimeList'dan topilmadi — ma'lumotlarni tekshiring",
        f"⚠️ {esc(note)}" if note else "",
        "",
        f"🆔 <code>{d['anime_id']}</code>  •  📝 <b>{esc(d['title'])}</b>",
        f"📁 Tur: {TYPE_LABEL.get(d.get('content_type'), d.get('content_type'))}",
        f"🎭 Janr: {esc(genres)}",
        f"🏷 Teglar: {esc(tags)}",
        f"😌 Mood: {esc(mood)}",
        f"📅 Yil: {d.get('year') or '—'}  •  ⭐ Reyting: {d.get('rating') or '—'}",
        f"🎞 Qismlar: {d.get('episodes_count') or '—'}  •  ⏱ {d.get('duration') or '—'} daq",
        f"📊 Status: {STATUS_LABEL.get(d.get('status'), d.get('status'))}",
        "🖼 Inline rasm: " + ("✅ bor" if d.get("inline_thumbnail_url") else "⚠️ yo'q (qidiruvda rasm chiqmaydi)"),
        "",
        f"📖 {esc(desc)}",
        "",
        "<b>To'g'rimi?</b>",
    ]
    return "\n".join(lines)


def _render_preview(data: dict) -> str:
    """Joriy FSM qiymatlaridan (tahrirlar hisobga olingan holda) ko'rinish matni."""
    ai = data.get("ai") or {}
    merged = {**data, "sources": ai.get("sources"), "matched_title": ai.get("matched_title"), "note": ai.get("note")}
    return _preview_text(merged)


@ai_admin_router.message(AddAnimeAI.waiting_english, F.text)
async def ai_get_english(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    if msg.text == CANCEL_TEXT:
        return await _cancel(msg, state)
    english = msg.text.strip()
    if not english:
        return await msg.answer("❌ Nom bo'sh bo'la olmaydi.")

    wait = await msg.answer("⏳ AI ma'lumot yig'ayapti...")
    try:
        info = await build_content_info(english)
    except Exception:
        logger.exception("build_content_info xato")
        info = {"content_type": "anime", "sources": [], "genres": [], "tags": [], "mood": [], "status": "ongoing"}
    try:
        await wait.delete()
    except Exception:
        pass

    data = await state.get_data()
    await state.update_data(
        english_title=english,
        ai=info,
        content_type=info.get("content_type", "anime"),
        desc=info.get("desc", ""),
        genres=info.get("genres", []),
        tags=info.get("tags", []),
        mood=info.get("mood", []),
        year=info.get("year"),
        rating=info.get("rating", 0.0),
        total_episodes=info.get("total_episodes", 0),
        episodes_count=info.get("episodes_count", 0),
        duration=info.get("duration"),
        status=info.get("status", "ongoing"),
        popularity=0.0,
        related=[],
        is_pro_locked=False,
        is_hidden_gem=False,
        season=1,
    )
    await state.set_state(AddAnimeAI.confirm)
    await msg.answer(_render_preview(await state.get_data()), parse_mode="HTML", reply_markup=_confirm_kb())


# ─── 6) Tasdiqlash ────────────────────────────────────────────────────

@ai_admin_router.callback_query(F.data == "aiadd_ok", AddAnimeAI.confirm)
async def ai_confirm_ok(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    await call.answer("Saqlanmoqda...")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    # _save_anime msg.from_user.id orqali egasini (partner/admin) aniqlaydi —
    # callback xabarining from_user'i bot bo'lgani uchun bosgan odamni qo'yamiz.
    msg = call.message.model_copy(update={"from_user": call.from_user})
    await _save_anime(msg, state, call.bot)  # saqlaydi + kanalga post so'raydi


@ai_admin_router.callback_query(F.data == "aiadd_retry", AddAnimeAI.confirm)
async def ai_confirm_retry(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    await state.set_state(AddAnimeAI.waiting_english)
    await call.message.answer(
        "🔎 <b>Inglizcha nomini qayta yuboring</b> (aniqroq yozing):",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )
    await call.answer()


@ai_admin_router.callback_query(F.data == "aiadd_manual", AddAnimeAI.confirm)
async def ai_confirm_manual(call: types.CallbackQuery, state: FSMContext):
    """Oddiy (qo'lda) oqimga o'tish — ID, nom, poster va treyler saqlanib qoladi."""
    if not await is_admin(call.from_user.id):
        return await call.answer()
    data = await state.get_data()
    keep = {k: data.get(k) for k in ("anime_id", "title", "poster_file_id", "inline_thumbnail_url", "trailer_file_id")}
    await state.clear()
    await state.update_data(**keep, base_title=_strip_season_suffix(keep["title"]), season=1)
    await state.set_state(AddAnime.waiting_type)
    await call.message.answer(
        "✍️ <b>Qo'lda davom etamiz.</b>\n"
        "ID, nom, poster va treyler saqlandi (poster/treyler so'ralganda «O'tkazib yuborish» ni bossangiz o'sha qoladi).\n\n"
        "📁 <b>Tur:</b>",
        parse_mode="HTML",
        reply_markup=TYPE_KB,
    )
    await call.answer()


@ai_admin_router.callback_query(F.data == "aiadd_cancel")
async def ai_confirm_cancel(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    await state.clear()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer("❌ Bekor qilindi.", reply_markup=admin_main_kb)
    await call.answer()


# ─── 7) Tahrirlash ────────────────────────────────────────────────────

EDIT_FIELDS = [
    ("title", "📝 Nom"), ("content_type", "📁 Tur"),
    ("genres", "🎭 Janr"), ("tags", "🏷 Teglar"),
    ("mood", "😌 Mood"), ("status", "📊 Status"),
    ("year", "📅 Yil"), ("rating", "⭐ Reyting"),
    ("episodes_count", "🎞 Qismlar"), ("duration", "⏱ Davomiylik"),
    ("desc", "📖 Tavsif"), ("inline_thumbnail_url", "🖼 Inline rasm"),
]
EDIT_HINTS = {
    "title": "Yangi nomni yuboring.",
    "genres": "Janrlarni vergul bilan yozing. Masalan: <code>Jang, Fantaziya, Drama</code>",
    "tags": "Teglarni vergul bilan yozing (inglizcha). Masalan: <code>revenge, magic</code>",
    "mood": f"Mood'larni vergul bilan yozing. Masalan: <code>dark, emotional</code>\nMumkin: {esc(', '.join(__import__('utils.ai_anime', fromlist=['ALLOWED_MOODS']).ALLOWED_MOODS))}",
    "year": "Yilni yozing (masalan <code>2026</code>) yoki tozalash uchun <code>-</code>.",
    "rating": "Reytingni yozing, 0 dan 10 gacha (masalan <code>8.4</code>) yoki <code>-</code>.",
    "episodes_count": "Qismlar sonini yozing (masalan <code>12</code>).",
    "duration": "Bir qism davomiyligini daqiqada yozing (masalan <code>24</code>) yoki <code>-</code>.",
    "desc": "Yangi tavsifni yuboring (1-1500 belgi).",
    "inline_thumbnail_url": "Kvadrat/portret <b>rasm</b> yuboring (o'zim URL qilaman) yoki <b>https://</b> URL yozing.",
}


def _edit_menu_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for key, label in EDIT_FIELDS:
        row.append(InlineKeyboardButton(text=sym(label), callback_data=f"aiedit:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="ᐊ Orqaga", callback_data="aiedit_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _enum_kb(field: str) -> InlineKeyboardMarkup:
    options = TYPE_LABEL if field == "content_type" else STATUS_LABEL
    rows = [[InlineKeyboardButton(text=sym(label), callback_data=f"aival:{field}:{val}")]
            for val, label in options.items()]
    rows.append([InlineKeyboardButton(text="ᐊ Orqaga", callback_data="aiadd_edit")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _refresh_preview(message: Message, state: FSMContext) -> None:
    """Mavjud ko'rinish xabarini yangilangan matn bilan almashtiradi."""
    await message.edit_text(_render_preview(await state.get_data()), parse_mode="HTML", reply_markup=_confirm_kb())


@ai_admin_router.callback_query(F.data == "aiadd_edit", AddAnimeAI.confirm)
async def ai_edit_menu(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    await call.message.edit_reply_markup(reply_markup=_edit_menu_kb())
    await call.answer("Qaysi maydonni o'zgartiramiz?")


@ai_admin_router.callback_query(F.data == "aiedit_back", AddAnimeAI.confirm)
async def ai_edit_back(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    await call.message.edit_reply_markup(reply_markup=_confirm_kb())
    await call.answer()


@ai_admin_router.callback_query(F.data.startswith("aiedit:"), AddAnimeAI.confirm)
async def ai_edit_pick(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    field = call.data.split(":", 1)[1]
    if field in ("content_type", "status"):
        await call.message.edit_reply_markup(reply_markup=_enum_kb(field))
        return await call.answer()
    if field not in EDIT_HINTS:
        return await call.answer("Noma'lum maydon")
    current = (await state.get_data()).get(field)
    if isinstance(current, list):
        current = ", ".join(current)
    if field == "inline_thumbnail_url":
        current = "✅ bor" if current else "yo'q"  # URL ichida maxfiy qism bo'lishi mumkin — ko'rsatmaymiz
    await state.update_data(edit_field=field, preview_msg_id=call.message.message_id)
    await state.set_state(AddAnimeAI.editing)
    await call.message.answer(
        f"✏️ <b>{dict(EDIT_FIELDS)[field]}</b>\n"
        f"Hozir: <code>{esc(str(current if current not in (None, '') else '—'))[:300]}</code>\n\n"
        f"{EDIT_HINTS[field]}",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )
    await call.answer()


@ai_admin_router.callback_query(F.data.startswith("aival:"), AddAnimeAI.confirm)
async def ai_edit_enum(call: types.CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return await call.answer()
    _, field, value = call.data.split(":", 2)
    allowed = TYPE_LABEL if field == "content_type" else STATUS_LABEL
    if field not in ("content_type", "status") or value not in allowed:
        return await call.answer("Noto'g'ri qiymat")
    await state.update_data(**{field: value})
    await _refresh_preview(call.message, state)
    await call.answer("✅ O'zgartirildi")


def _parse_edit(field: str, raw: str):
    """(qiymat, xato_matni) qaytaradi."""
    from handlers.genres import normalize_genre
    from utils.ai_anime import ALLOWED_MOODS

    raw = raw.strip()
    clear = raw in ("-", "—")
    if field == "inline_thumbnail_url":
        return (raw, None) if raw.startswith("http") else (None, "Rasm yuboring yoki https:// bilan boshlanadigan URL yozing.")
    if field == "title":
        return (raw, None) if raw else (None, "Nom bo'sh bo'lmasin.")
    if field == "desc":
        if not raw or clear:
            return None, "Tavsif bo'sh bo'lmasin."
        return raw[:1500], None
    if field in ("tags", "mood", "genres"):
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        if field == "genres":
            good = [g for g in dict.fromkeys(normalize_genre(p) for p in parts) if g in GENRES]
            bad = [p for p in parts if normalize_genre(p) not in GENRES]
            if not good:
                return None, "Janr topilmadi. Mumkin: " + ", ".join(GENRES.keys())
            if bad:
                return None, f"Tanilmadi: {', '.join(bad)}. Mumkin: " + ", ".join(GENRES.keys())
            return good, None
        parts = [p.lower() for p in parts]
        if field == "mood":
            bad = [p for p in parts if p not in ALLOWED_MOODS]
            if bad:
                return None, f"Tanilmadi: {', '.join(bad)}. Mumkin: {', '.join(ALLOWED_MOODS)}"
        return list(dict.fromkeys(parts))[:8], None
    if field in ("year", "duration", "rating") and clear:
        return (0.0 if field == "rating" else None), None
    try:
        if field == "rating":
            val = float(raw.replace(",", "."))
            return (round(val, 1), None) if 0 <= val <= 10 else (None, "Reyting 0 dan 10 gacha bo'lsin.")
        val = int(raw)
    except ValueError:
        return None, "Faqat son yozing."
    if field == "year" and not 1950 <= val <= 2100:
        return None, "Yil 1950–2100 oralig'ida bo'lsin."
    if field in ("episodes_count", "duration") and not 0 <= val <= 5000:
        return None, "0 dan 5000 gacha son yozing."
    return val, None


@ai_admin_router.message(AddAnimeAI.editing, F.text)
async def ai_edit_value(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    data = await state.get_data()
    field = data.get("edit_field")
    if msg.text != CANCEL_TEXT:
        value, error = _parse_edit(field, msg.text)
        if error:
            return await msg.answer(f"❌ {error}\nQayta yuboring yoki «{CANCEL_TEXT}» ni bosing.", parse_mode="HTML")
        update = {field: value}
        if field == "episodes_count":
            update["total_episodes"] = value
        await state.update_data(**update)
    await state.set_state(AddAnimeAI.confirm)
    await msg.answer("✅ Yangilandi." if msg.text != CANCEL_TEXT else "Bekor qilindi.", reply_markup=admin_main_kb)
    await msg.answer(_render_preview(await state.get_data()), parse_mode="HTML", reply_markup=_confirm_kb())


@ai_admin_router.message(AddAnimeAI.editing, F.photo)
async def ai_edit_photo(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    data = await state.get_data()
    if data.get("edit_field") != "inline_thumbnail_url":
        return await msg.answer("❌ Bu maydon uchun matn yuboring.")
    photo = msg.photo[-1]
    if photo.height and photo.width / photo.height > 1.05:
        return await msg.answer("❌ Bu rasm keng. Kvadrat yoki portret rasm yuboring (yoki URL).")
    url = await _photo_to_url(msg.bot, photo, f"inline_{data['anime_id']}")
    if not url:
        return await msg.answer("❌ Rasmdan URL olinmadi. URL yuboring.")
    await state.update_data(inline_thumbnail_url=url)
    await state.set_state(AddAnimeAI.confirm)
    await msg.answer("✅ Yangilandi.", reply_markup=admin_main_kb)
    await msg.answer(_render_preview(await state.get_data()), parse_mode="HTML", reply_markup=_confirm_kb())
