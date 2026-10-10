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

logger = logging.getLogger(__name__)
ai_admin_router = Router()

CANCEL_TEXT = "🚫 Bekor qilish"
TYPE_LABEL = {"anime": "🎌 Anime", "movie": "🎥 Kino", "serial": "📺 Serial", "dorama": "🌸 Dorama"}
STATUS_LABEL = {"ongoing": "📡 Davom etmoqda", "completed": "✅ Tugagan", "announced": "📢 Kutilmoqda"}


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ To'g'ri, saqlash", callback_data="aiadd_ok", style="success")],
            [
                InlineKeyboardButton(text="🔄 AI bilan qaytadan", callback_data="aiadd_retry", style="primary"),
                InlineKeyboardButton(text="✍️ Qo'lda davom", callback_data="aiadd_manual", style="primary"),
            ],
            [InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="aiadd_cancel", style="danger")],
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


@ai_admin_router.message(AddAnimeAI.waiting_poster, F.photo)
async def ai_get_poster(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    photo = msg.photo[-1]
    rejection = _poster_rejection_reason(photo)
    if rejection:
        return await msg.answer(rejection + "\nIltimos, kichikroq rasm yuboring.")

    inline_url = None
    portrait = (photo.width / photo.height if photo.height else 1.0) <= 1.05
    if portrait:  # inline qidiruv uchun faqat portret/kvadrat yaroqli
        try:
            from utils.imgbb import upload_telegram_photo_to_imgbb

            if getattr(config, "IMGBB_API_KEY", ""):
                inline_url = await upload_telegram_photo_to_imgbb(
                    msg.bot, photo.file_id, config.IMGBB_API_KEY, name=f"poster_{(await state.get_data())['anime_id']}"
                )
        except Exception:
            logger.warning("ImgBB xato", exc_info=True)
        if not inline_url:
            inline_url = await _get_telegram_file_url(msg.bot, photo.file_id)
    # Landscape bo'lsa — inline URL keyinroq AI (MyAnimeList) rasmidan olinadi.
    await state.update_data(poster_file_id=photo.file_id, inline_thumbnail_url=inline_url)
    await state.set_state(AddAnimeAI.waiting_trailer)
    await _ask_trailer(msg)


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
    lines = [
        f"🤖 <b>AI natijasi</b>  <i>({esc(src)})</i>",
        f"🔗 Topilgan nom: <b>{esc(matched)}</b>" if matched else "⚠️ MyAnimeList'dan topilmadi — ma'lumotlarni tekshiring",
        "",
        f"🆔 <code>{d['anime_id']}</code>  •  📝 <b>{esc(d['title'])}</b>",
        f"📁 Tur: {TYPE_LABEL.get(d.get('content_type'), d.get('content_type'))}",
        f"🎭 Janr: {esc(genres)}",
        f"🏷 Teglar: {esc(tags)}",
        f"😌 Mood: {esc(mood)}",
        f"📅 Yil: {d.get('year') or '—'}  •  ⭐ Reyting: {d.get('rating') or '—'}",
        f"🎞 Qismlar: {d.get('episodes_count') or '—'}  •  ⏱ {d.get('duration') or '—'} daq",
        f"📊 Status: {STATUS_LABEL.get(d.get('status'), d.get('status'))}",
        "",
        f"📖 {esc(desc)}",
        "",
        "<b>To'g'rimi?</b>",
    ]
    return "\n".join(lines)


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
    # Poster landscape bo'lsa — MyAnimeList portret rasmini inline uchun ishlatamiz
    if not data.get("inline_thumbnail_url") and info.get("image_url"):
        await state.update_data(inline_thumbnail_url=info["image_url"])
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
    data = await state.get_data()
    await msg.answer(_preview_text({**data, **info, "anime_id": data["anime_id"], "title": data["title"]}),
                     parse_mode="HTML", reply_markup=_confirm_kb())


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
