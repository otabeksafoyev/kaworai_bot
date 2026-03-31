"""
Kaworai Pro — Pro User Handler (tuzatilgan)
Barcha edit_caption → safe_edit() orqali ishlaydi.
"""

from aiogram import Router, F, types
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.engine import AsyncSessionLocal
from database.models import User, Anime
from datetime import datetime
from sqlalchemy import select

pro_user_router = Router()


# ═══════════════════════════════════════════════════════════
#  UNIVERSAL EDIT YORDAMCHI — asosiy tuzatish
# ═══════════════════════════════════════════════════════════

async def safe_edit(call: types.CallbackQuery, text: str, reply_markup=None):
    """
    Xabar turi (rasm/video vs matn) ga qarab to'g'ri edit usulini ishlatadi.
    caption bo'lsa → edit_caption
    matn bo'lsa   → edit_text
    Ikkalasi ham ishlamasa → yangi xabar yuboradi.
    """
    msg = call.message
    try:
        if msg.caption is not None:
            await msg.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await msg.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    except Exception:
        try:
            await msg.answer(
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#  PRO TEKSHIRISH
# ═══════════════════════════════════════════════════════════

async def check_pro(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.is_pro:
            return False
        if user.pro_until and user.pro_until < datetime.utcnow():
            user.is_pro    = False
            user.pro_until = None
            await session.commit()
            return False
        return True


# ═══════════════════════════════════════════════════════════
#  KONTENT KARTOCHKASI
# ═══════════════════════════════════════════════════════════

def format_card(item: dict) -> str:
    genres = ", ".join(item.get("genres", [])[:3]) or "—"
    tags   = ", ".join(item.get("tags",   [])[:3]) or "—"
    mood   = ", ".join(item.get("mood",   [])[:2]) or "—"

    type_emoji = {"anime": "🎌", "movie": "🎥", "serial": "📺", "dorama": "🌸"}
    emoji = type_emoji.get(item.get("type", "anime"), "🎬")

    status_map = {
        "completed": "✅ Tugagan",
        "ongoing":   "📡 Davom etmoqda",
        "announced": "📢 Kutilmoqda",
    }
    status   = status_map.get(item.get("status", ""), "")
    ep_text  = f"🎞 {item['episodes']} qism" if item.get("episodes") else ""
    year     = f" ({item['year']})" if item.get("year") else ""

    lines = [f"{emoji} <b>{item['title']}</b>{year}"]
    if genres != "—": lines.append(f"🎭 {genres}")
    if tags   != "—": lines.append(f"🏷 {tags}")
    if mood   != "—": lines.append(f"😌 {mood}")

    rating_line = f"⭐ {item.get('rating', 0):.1f}"
    if ep_text: rating_line += f" | {ep_text}"
    if status:  rating_line += f" | {status}"
    lines.append(rating_line)

    if item.get("is_hidden_gem"): lines.append("💎 <b>Hidden Gem!</b>")
    if item.get("locked"):        lines.append("🔒 <i>Faqat Pro uchun</i>")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  PRO MENYU (pro_payment.py dan chaqiriladi)
# ═══════════════════════════════════════════════════════════

async def show_pro_main_menu(call: types.CallbackQuery):
    """Pro bo'lgan user uchun asosiy menyu."""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, call.from_user.id)
        until_str = ""
        if user and user.pro_until:
            until_str = f"\n📅 Tugash: <b>{user.pro_until.strftime('%d.%m.%Y')}</b>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🤖 AI Tavsiyalar",  callback_data="pro_recommend"),
            InlineKeyboardButton(text="😌 Kayfiyatim",     callback_data="pro_mood"),
        ],
        [
            InlineKeyboardButton(text="🔥 Trending",       callback_data="pro_trending"),
            InlineKeyboardButton(text="⭐ Top reyting",     callback_data="pro_top"),
        ],
        [
            InlineKeyboardButton(text="📈 Rising",         callback_data="pro_rising"),
            InlineKeyboardButton(text="💎 Hidden Gems",    callback_data="pro_hidden"),
        ],
        [
            InlineKeyboardButton(text="▶️ Davom ettirish", callback_data="pro_continue"),
            InlineKeyboardButton(text="👤 Mening didim",   callback_data="pro_taste"),
        ],
        [InlineKeyboardButton(text="🏠 Asosiy menyu",      callback_data="main_menu")],
    ])

    text = (
        f"⚡ <b>Kaworai Pro</b>\n\n"
        f"✅ Siz Pro foydalanuvchisiz!{until_str}\n\n"
        "Nima qilmoqchisiz?"
    )
    await safe_edit(call, text, kb)
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  AI TAVSIYALAR
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data == "pro_recommend")
async def pro_recommend(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    await safe_edit(call, "🤖 Sizga mos kontentlar hisoblanmoqda...")

    try:
        from utils.recommendation import get_recommendations, get_or_create_taste_profile, build_identity_label
        async with AsyncSessionLocal() as session:
            recs    = await get_recommendations(session, call.from_user.id, limit=8, is_pro=True)
            profile = await get_or_create_taste_profile(session, call.from_user.id)
            identity = build_identity_label(profile)
    except Exception:
        recs     = []
        identity = "🎌 Anime muxlisi"

    if not recs:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Orqaga", callback_data="kawaii_pass")]
        ])
        await safe_edit(
            call,
            "😕 Hozircha tavsiya yo'q.\nKo'proq kontent ko'ring — tizim sizni o'rganib boradi!",
            kb
        )
        return await call.answer()

    await _show_rec_item(call, recs, 0, identity)
    await call.answer()


async def _show_rec_item(call: types.CallbackQuery, recs: list, idx: int, identity: str = ""):
    item = recs[idx]
    desc = (item.get("description") or "")[:150]
    text = (
        f"🤖 <b>AI Tavsiya</b> ({idx+1}/{len(recs)})\n"
        + (f"<i>{identity}</i>\n" if idx == 0 and identity else "")
        + f"\n{format_card(item)}\n\n"
        + (f"📖 {desc}..." if desc else "")
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="▶️ Ko'rish", callback_data=f"watch_{item['id']}"))
    if idx + 1 < len(recs):
        kb.row(InlineKeyboardButton(
            text=f"⏭ Keyingi ({idx+2}/{len(recs)})",
            callback_data=f"pro_rec_{idx+1}"
        ))
    kb.row(
        InlineKeyboardButton(text="🔗 O'xshashlar", callback_data=f"related_{item['id']}"),
        InlineKeyboardButton(text="↩️ Orqaga",      callback_data="kawaii_pass"),
    )
    await safe_edit(call, text, kb.as_markup())


@pro_user_router.callback_query(F.data.startswith("pro_rec_"))
async def pro_rec_next(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    idx = int(call.data.replace("pro_rec_", ""))

    try:
        from utils.recommendation import get_recommendations
        async with AsyncSessionLocal() as session:
            recs = await get_recommendations(session, call.from_user.id, limit=8, is_pro=True)
    except Exception:
        recs = []

    if not recs or idx >= len(recs):
        return await call.answer("🔚 Tavsiyalar tugadi!", show_alert=True)

    await _show_rec_item(call, recs, idx)
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  MOOD AI
# ═══════════════════════════════════════════════════════════

MOOD_LABELS = {
    "sad":          "😢 G'amgin",
    "romantic":     "💕 Romantik",
    "dark":         "🌑 Dark",
    "motivational": "💪 Motivatsion",
    "action":       "⚔️ Jangari",
    "funny":        "😂 Kulgili",
    "mystery":      "🔍 Sirli",
    "chill":        "🌸 Chill",
    "fantasy":      "🧙 Fantastik",
    "scary":        "😱 Qo'rqinchli",
}


@pro_user_router.callback_query(F.data == "pro_mood")
async def pro_mood_menu(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    kb = InlineKeyboardBuilder()
    for mood, label in MOOD_LABELS.items():
        kb.row(InlineKeyboardButton(text=label, callback_data=f"pmood_{mood}"))
    kb.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="kawaii_pass"))

    await safe_edit(
        call,
        "😌 <b>Hozirgi kayfiyatingiz?</b>\n\nKayfiyatingizga mos kontentlarni topib beraman!",
        kb.as_markup()
    )
    await call.answer()


@pro_user_router.callback_query(F.data.startswith("pmood_"))
async def mood_selected(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    mood = call.data.replace("pmood_", "")
    label = MOOD_LABELS.get(mood, mood.capitalize())

    await safe_edit(call, f"🔍 {label} kayfiyatga mos kontentlar qidirilmoqda...")

    try:
        from utils.recommendation import get_recommendations
        async with AsyncSessionLocal() as session:
            recs = await get_recommendations(
                session, call.from_user.id,
                target_moods=[mood], limit=6, is_pro=True
            )
    except Exception:
        recs = []

    if not recs:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Orqaga", callback_data="pro_mood")]
        ])
        await safe_edit(call, f"😕 {label} kayfiyatga mos kontent topilmadi.", kb)
        return await call.answer()

    await _show_mood_item(call, recs, 0, mood, label)
    await call.answer()


async def _show_mood_item(call, recs, idx, mood, label):
    item = recs[idx]
    desc = (item.get("description") or "")[:150]
    text = (
        f"{label} <b>Kayfiyatga Mos</b> ({idx+1}/{len(recs)})\n\n"
        f"{format_card(item)}\n\n"
        + (f"📖 {desc}..." if desc else "")
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="▶️ Ko'rish", callback_data=f"watch_{item['id']}"))
    if idx + 1 < len(recs):
        kb.row(InlineKeyboardButton(
            text=f"⏭ Keyingi ({idx+2}/{len(recs)})",
            callback_data=f"pmood_next_{mood}_{idx+1}"
        ))
    kb.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="pro_mood"))
    await safe_edit(call, text, kb.as_markup())


@pro_user_router.callback_query(F.data.startswith("pmood_next_"))
async def mood_next(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    # pmood_next_{mood}_{idx}
    raw   = call.data.replace("pmood_next_", "")
    parts = raw.rsplit("_", 1)
    mood  = parts[0]
    idx   = int(parts[1])
    label = MOOD_LABELS.get(mood, mood.capitalize())

    try:
        from utils.recommendation import get_recommendations
        async with AsyncSessionLocal() as session:
            recs = await get_recommendations(
                session, call.from_user.id,
                target_moods=[mood], limit=6, is_pro=True
            )
    except Exception:
        recs = []

    if not recs or idx >= len(recs):
        return await call.answer("🔚 Tugadi!", show_alert=True)

    await _show_mood_item(call, recs, idx, mood, label)
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  TRENDING / TOP / RISING / HIDDEN GEMS
# ═══════════════════════════════════════════════════════════

async def _show_list(call: types.CallbackQuery, items: list, title: str, back_cb: str = "kawaii_pass"):
    if not items:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Orqaga", callback_data=back_cb)]
        ])
        await safe_edit(call, f"{title}\n\n😕 Hozircha ma'lumot yo'q.", kb)
        await call.answer()
        return

    kb   = InlineKeyboardBuilder()
    text = f"{title}\n\n"

    for i, item in enumerate(items[:6], 1):
        genres = ", ".join(item.get("genres", [])[:2]) or "—"
        lock   = "🔒 " if item.get("locked") else ""
        text  += f"{i}. {lock}<b>{item['title']}</b> ({item.get('year', '—')})\n"
        text  += f"   ⭐ {item.get('rating', 0):.1f}  🎭 {genres}\n\n"

        if item.get("locked"):
            kb.row(InlineKeyboardButton(
                text=f"🔒 {item['title'][:28]}",
                callback_data="pro_upgrade_hint"
            ))
        else:
            kb.row(InlineKeyboardButton(
                text=f"▶️ {item['title'][:28]}",
                callback_data=f"watch_{item['id']}"
            ))

    kb.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data=back_cb))
    await safe_edit(call, text, kb.as_markup())
    await call.answer()


@pro_user_router.callback_query(F.data == "pro_trending")
async def pro_trending(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)
    try:
        from utils.recommendation import get_trending
        async with AsyncSessionLocal() as session:
            items = await get_trending(session, limit=6, is_pro=True)
    except Exception:
        items = []
    await _show_list(call, items, "🔥 <b>Trending — Bu hafta eng ko'p ko'rilganlar</b>")


@pro_user_router.callback_query(F.data == "pro_top")
async def pro_top(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)
    try:
        from utils.recommendation import get_top_rated
        async with AsyncSessionLocal() as session:
            items = await get_top_rated(session, limit=6, is_pro=True)
    except Exception:
        items = []
    await _show_list(call, items, "⭐ <b>Top Reyting — Eng yuqori baholangan</b>")


@pro_user_router.callback_query(F.data == "pro_rising")
async def pro_rising(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)
    try:
        from utils.recommendation import get_rising
        async with AsyncSessionLocal() as session:
            items = await get_rising(session, limit=6, is_pro=True)
    except Exception:
        items = []
    await _show_list(call, items, "📈 <b>Rising — Tez o'sayotgan kontentlar</b>")


@pro_user_router.callback_query(F.data == "pro_hidden")
async def pro_hidden_gems(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)
    try:
        from utils.recommendation import get_hidden_gems
        async with AsyncSessionLocal() as session:
            items = await get_hidden_gems(session, limit=6)
    except Exception:
        items = []
    await _show_list(call, items, "💎 <b>Hidden Gems — Kam mashhur, lekin oltin!</b>")


# ═══════════════════════════════════════════════════════════
#  RELATED CONTENT
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data.startswith("related_"))
async def show_related(call: types.CallbackQuery):
    anime_id = int(call.data.replace("related_", ""))
    is_pro   = await check_pro(call.from_user.id)

    try:
        from utils.recommendation import get_related_content
        async with AsyncSessionLocal() as session:
            items = await get_related_content(session, anime_id, limit=5, is_pro=is_pro)
            anime = await session.get(Anime, anime_id)
        title = anime.title if anime else "Bu kontent"
    except Exception:
        items = []
        title = "Bu kontent"

    if not items:
        return await call.answer("😕 O'xshash kontent topilmadi.", show_alert=True)

    await _show_list(call, items, f"🔗 <b>{title}</b> bilan o'xshashlar")


# ═══════════════════════════════════════════════════════════
#  SMART CONTINUE
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data == "pro_continue")
async def pro_smart_continue(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    try:
        from utils.recommendation import get_smart_continue
        async with AsyncSessionLocal() as session:
            items = await get_smart_continue(session, call.from_user.id)
    except Exception:
        items = []

    kb = InlineKeyboardBuilder()

    if not items:
        kb.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="kawaii_pass"))
        await safe_edit(
            call,
            "▶️ <b>Smart Continue</b>\n\nHozircha davom ettiriladigan kontent yo'q.\nBiror nima ko'rishni boshlang! 😊",
            kb.as_markup()
        )
        return await call.answer()

    text = "▶️ <b>Smart Continue — Qolgan joydan davom eting</b>\n\n"
    for item in items:
        ep = item.get("resume_from", 1)
        text += f"🎬 <b>{item['title']}</b> — {ep}-qismdan\n"
        kb.row(InlineKeyboardButton(
            text=f"▶️ {item['title'][:22]} — {ep}-qism",
            callback_data=f"watch_{item['id']}"
        ))

    kb.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="kawaii_pass"))
    await safe_edit(call, text, kb.as_markup())
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  TASTE PROFILE
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data == "pro_taste")
async def pro_taste_profile(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    try:
        from utils.recommendation import get_or_create_taste_profile, build_identity_label
        async with AsyncSessionLocal() as session:
            profile  = await get_or_create_taste_profile(session, call.from_user.id)
        identity = build_identity_label(profile)

        genres    = dict(profile.fav_genres or {})
        top_g     = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:3]
        g_text    = "\n".join(f"  • {g}: {c} marta" for g, c in top_g) or "  Hali ma'lumot yo'q"

        tags      = dict(profile.fav_tags or {})
        top_t     = sorted(tags.items(), key=lambda x: x[1], reverse=True)[:3]
        t_text    = "\n".join(f"  • {t}: {c} marta" for t, c in top_t) or "  Hali ma'lumot yo'q"

        moods     = dict(profile.fav_moods or {})
        top_m     = sorted(moods.items(), key=lambda x: x[1], reverse=True)[:2]
        m_text    = ", ".join(m for m, _ in top_m) or "Aniqlanmagan"

        type_map  = {"anime": "🎌 Anime", "movie": "🎥 Kino", "serial": "📺 Serial", "dorama": "🌸 Dorama"}
        fav_type  = type_map.get(profile.fav_type or "anime", "🎌 Anime")
    except Exception:
        identity  = "🎌 Anime muxlisi"
        g_text    = "  Hali ma'lumot yo'q"
        t_text    = "  Hali ma'lumot yo'q"
        m_text    = "Aniqlanmagan"
        fav_type  = "🎌 Anime"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🤖 Tavsiyalar", callback_data="pro_recommend"),
            InlineKeyboardButton(text="↩️ Orqaga",     callback_data="kawaii_pass"),
        ]
    ])

    text = (
        f"👤 <b>Sizning Did Profilingiz</b>\n\n"
        f"🎯 <b>{identity}</b>\n\n"
        f"🎭 <b>Sevimli janrlar:</b>\n{g_text}\n\n"
        f"🏷 <b>Sevimli teglar:</b>\n{t_text}\n\n"
        f"😌 <b>Sevimli mood:</b> {m_text}\n"
        f"📁 <b>Sevimli tur:</b> {fav_type}\n\n"
        f"<i>Ko'rgan kontentlaringiz asosida yig'iladi.</i>"
    )
    await safe_edit(call, text, kb)
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  MISC
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data == "pro_upgrade_hint")
async def pro_upgrade_hint(call: types.CallbackQuery):
    await call.answer(
        "🔒 Bu kontent Kaworai Pro uchun!\n"
        "Pro bo'lish uchun 🟢 Kaworai Pro tugmasini bosing.",
        show_alert=True
    )