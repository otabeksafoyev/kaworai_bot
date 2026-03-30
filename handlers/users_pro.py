"""
Kaworai Pro — Pro User Handler
users.py ga QO'SHILADI.

Mavjud users.py da "kawaii_pass" callback bo'sh edi.
Bu fayl uni to'liq Pro tizimga ulaydi.

FOYDALANISH:
  bot.py yoki main.py ga:
  from handlers.users_pro import pro_user_router
  dp.include_router(pro_user_router)
"""

from aiogram import Router, F, types
from aiogram.types import Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.engine import AsyncSessionLocal
from database.models import User, Anime
from utils.recommendation import (
    get_recommendations,
    get_trending,
    get_top_rated,
    get_rising,
    get_hidden_gems,
    get_related_content,
    get_next_recommendation,
    get_smart_continue,
    get_pro_locked_teaser,
    detect_mood_from_text,
    mood_to_filters,
    MOOD_MAP,
    build_identity_label,
    get_or_create_taste_profile,
    add_to_watch_history,
    record_view,
)
from datetime import datetime
from sqlalchemy import select

pro_user_router = Router()


# ═══════════════════════════════════════════════════════════
#  YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════

async def check_pro(user_id: int) -> bool:
    """User Pro ekanligini tekshiradi."""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user or not user.is_pro:
            return False
        if user.pro_until and user.pro_until < datetime.utcnow():
            # Muddati o'tgan
            user.is_pro    = False
            user.pro_until = None
            await session.commit()
            return False
        return True


def format_content_card(item: dict, show_score: bool = False) -> str:
    """Kontent kartochkasini matn sifatida formatlaydi."""
    genres = ", ".join(item.get("genres", [])[:3]) or "—"
    tags   = ", ".join(item.get("tags",   [])[:3]) or "—"
    mood   = ", ".join(item.get("mood",   [])[:2]) or "—"
    status_map = {"completed": "✅ Tugagan", "ongoing": "📡 Davom etmoqda", "announced": "📢 Kutilmoqda"}
    type_emoji = {"anime": "🎌", "movie": "🎥", "serial": "📺", "dorama": "🌸"}

    emoji   = type_emoji.get(item.get("type", "anime"), "🎬")
    status  = status_map.get(item.get("status", ""), "")
    ep_text = f"🎞 {item.get('episodes')} qism" if item.get("episodes") else ""
    score_text = f"\n🤖 AI score: {item.get('score', 0):.2f}" if show_score else ""
    hidden_text = "\n💎 <b>Hidden Gem!</b>" if item.get("is_hidden_gem") else ""
    locked_text = "\n🔒 <i>Pro foydalanuvchilar uchun</i>" if item.get("locked") else ""
    relation = item.get("relation", "")
    rel_map = {"sequel": "➡️ Davomi", "prequel": "⬅️ Oldingi", "spin-off": "🔀 Spin-off",
               "also_watched": "👥 Ko'rganlar yoqtirdi", "similar": "🔗 O'xshash"}
    rel_text = f"\n{rel_map.get(relation, '')}" if relation else ""

    return (
        f"{emoji} <b>{item['title']}</b>"
        f"{' (' + str(item.get('year')) + ')' if item.get('year') else ''}\n"
        f"🎭 {genres}\n"
        f"🏷 {tags}\n"
        f"😌 Mood: {mood}\n"
        f"⭐ {item.get('rating', 0):.1f}"
        f"{' | ' + ep_text if ep_text else ''}"
        f"{' | ' + status if status else ''}"
        f"{rel_text}"
        f"{score_text}"
        f"{hidden_text}"
        f"{locked_text}"
    )


def build_content_keyboard(item: dict, is_pro: bool = True) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    if item.get("locked"):
        kb.row(InlineKeyboardButton(
            text="🔒 Pro bilan ko'rish",
            callback_data="pro_upgrade_hint"
        ))
    else:
        kb.row(InlineKeyboardButton(
            text="▶️ Ko'rish",
            callback_data=f"watch_{item['id']}"
        ))
        if is_pro:
            kb.row(InlineKeyboardButton(
                text="🔗 O'xshashlar",
                callback_data=f"related_{item['id']}"
            ))
    return kb


# ═══════════════════════════════════════════════════════════
#  KAWORAI PRO MENYU
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data == "kawaii_pass")
async def pro_menu(call: types.CallbackQuery):
    """Kaworai Pro asosiy menyu."""
    user_id = call.from_user.id
    is_pro  = await check_pro(user_id)

    if not is_pro:
        return await _show_pro_upgrade(call)

    # Taste profile
    async with AsyncSessionLocal() as session:
        profile = await get_or_create_taste_profile(session, user_id)
        identity = build_identity_label(profile)

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🤖 Menga mos tavsiyalar", callback_data="pro_recommend"),
        InlineKeyboardButton(text="😌 Kayfiyatim bo'yicha",  callback_data="pro_mood"),
    )
    kb.row(
        InlineKeyboardButton(text="🔥 Trending",      callback_data="pro_trending"),
        InlineKeyboardButton(text="⭐ Top reyting",    callback_data="pro_top"),
    )
    kb.row(
        InlineKeyboardButton(text="📈 Rising",         callback_data="pro_rising"),
        InlineKeyboardButton(text="💎 Hidden Gems",    callback_data="pro_hidden"),
    )
    kb.row(
        InlineKeyboardButton(text="▶️ Davom ettirish", callback_data="pro_continue"),
        InlineKeyboardButton(text="👤 Mening didim",   callback_data="pro_taste"),
    )
    kb.row(InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu"))

    await call.message.edit_caption(
        caption=(
            f"⚡ <b>Kaworai Pro</b>\n\n"
            f"🎯 <i>{identity}</i>\n\n"
            f"Nima qilmoqchisiz?"
        ),
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


async def _show_pro_upgrade(call: types.CallbackQuery):
    """Pro bo'lmagan userlarga upgrade ko'rsatish."""
    async with AsyncSessionLocal() as session:
        teasers = await get_pro_locked_teaser(session, limit=2)

    teaser_text = ""
    for t in teasers:
        teaser_text += f"\n🔒 <b>{t['title']}</b> ({t.get('year', '')})"

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✨ Pro olish", callback_data="pro_buy"))
    kb.row(InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu"))

    await call.message.edit_caption(
        caption=(
            "⚡ <b>Kaworai Pro</b>\n\n"
            "Pro foydalanuvchilar uchun:\n"
            "• 🤖 AI asosida shaxsiy tavsiyalar\n"
            "• 😌 Kayfiyatga mos kontent\n"
            "• 💎 Hidden Gems — kam mashhur durdonalar\n"
            "• 📈 Rising — tez oshayotgan kontentlar\n"
            "• ▶️ Smart Continue — qolgan joydan davom\n"
            "• 🔒 Maxsus Pro-only kontentlar\n\n"
            f"<b>Pro kontentlardan bir necha namuna:</b>{teaser_text}\n\n"
            "👆 Pro bo'ling va hammasi ochilsin!"
        ),
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@pro_user_router.callback_query(F.data == "pro_buy")
async def pro_buy(call: types.CallbackQuery):
    await call.answer(
        "📩 Pro olish uchun admin bilan bog'laning: @admin_username",
        show_alert=True
    )


# ═══════════════════════════════════════════════════════════
#  AI TAVSIYALAR
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data == "pro_recommend")
async def pro_recommend(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not await check_pro(user_id):
        return await call.answer("🔒 Bu funksiya Pro foydalanuvchilar uchun!", show_alert=True)

    await call.message.edit_caption(
        caption="🤖 Sizga mos kontentlar hisoblanmoqda...",
        parse_mode="HTML"
    )

    async with AsyncSessionLocal() as session:
        recs = await get_recommendations(session, user_id, limit=8, is_pro=True)
        profile = await get_or_create_taste_profile(session, user_id)
        identity = build_identity_label(profile)

    if not recs:
        return await call.message.edit_caption(
            caption="😕 Hozircha tavsiya yo'q. Ko'proq kontent ko'ring!",
            parse_mode="HTML"
        )

    # Birinchi tavsiyani ko'rsatish
    item = recs[0]
    text = (
        f"🤖 <b>AI Tavsiya</b>\n"
        f"<i>{identity}</i>\n\n"
        f"{format_content_card(item, show_score=False)}\n\n"
        f"📖 {(item.get('description') or '')[:150]}..."
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="▶️ Ko'rish",
        callback_data=f"watch_{item['id']}"
    ))
    kb.row(InlineKeyboardButton(
        text="⏭ Keyingi tavsiya",
        callback_data=f"pro_rec_next_1"  # index
    ))
    kb.row(
        InlineKeyboardButton(text="🔗 O'xshashlar", callback_data=f"related_{item['id']}"),
        InlineKeyboardButton(text="↩️ Orqaga",      callback_data="kawaii_pass"),
    )

    # Rasm bilan yoki rasmsiz
    poster = item.get("poster_file_id") or item.get("inline_thumbnail_url")
    try:
        if poster:
            await call.message.edit_media(
                types.InputMediaPhoto(media=poster, caption=text, parse_mode="HTML"),
                reply_markup=kb.as_markup()
            )
        else:
            await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")

    # Redis ga saqlash (keyingi navigatsiya uchun)
    # Oddiy: user_id → recs listni cache ga olish
    await call.answer()


@pro_user_router.callback_query(F.data.startswith("pro_rec_next_"))
async def pro_rec_next(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not await check_pro(user_id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    idx = int(call.data.replace("pro_rec_next_", ""))

    async with AsyncSessionLocal() as session:
        recs = await get_recommendations(session, user_id, limit=8, is_pro=True)

    if idx >= len(recs):
        return await call.answer("🔚 Tavsiyalar tugadi! Yangilarini qidirmoqdamiz...", show_alert=True)

    item = recs[idx]
    text = (
        f"🤖 <b>AI Tavsiya</b> ({idx+1}/{len(recs)})\n\n"
        f"{format_content_card(item)}\n\n"
        f"📖 {(item.get('description') or '')[:150]}..."
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="▶️ Ko'rish", callback_data=f"watch_{item['id']}"))
    if idx + 1 < len(recs):
        kb.row(InlineKeyboardButton(text="⏭ Keyingi", callback_data=f"pro_rec_next_{idx+1}"))
    kb.row(
        InlineKeyboardButton(text="🔗 O'xshashlar", callback_data=f"related_{item['id']}"),
        InlineKeyboardButton(text="↩️ Orqaga",      callback_data="kawaii_pass"),
    )

    poster = item.get("poster_file_id") or item.get("inline_thumbnail_url")
    try:
        if poster:
            await call.message.edit_media(
                types.InputMediaPhoto(media=poster, caption=text, parse_mode="HTML"),
                reply_markup=kb.as_markup()
            )
        else:
            await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  MOOD AI
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data == "pro_mood")
async def pro_mood_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not await check_pro(user_id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    kb = InlineKeyboardBuilder()
    moods_display = [
        ("😢 G'amgin",      "mood_sad"),
        ("💕 Romantik",     "mood_romantic"),
        ("🌑 Dark",         "mood_dark"),
        ("💪 Motivatsion",  "mood_motivational"),
        ("⚔️ Jangari",      "mood_action"),
        ("😂 Kulgili",      "mood_funny"),
        ("🔍 Sirli",        "mood_mystery"),
        ("🌸 Chill",        "mood_chill"),
        ("🧙 Fantastik",    "mood_fantasy"),
        ("😱 Qo'rqinchli",  "mood_scary"),
    ]
    for label, cdata in moods_display:
        kb.row(InlineKeyboardButton(text=label, callback_data=cdata))
    kb.row(InlineKeyboardButton(text="✍️ O'zim yozaman", callback_data="mood_custom"))
    kb.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="kawaii_pass"))

    await call.message.edit_caption(
        caption=(
            "😌 <b>Hozirgi kayfiyatingiz?</b>\n\n"
            "Kayfiyatingizga mos kontentlarni topib beraman!"
        ),
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@pro_user_router.callback_query(F.data.startswith("mood_") & ~F.data.startswith("mood_custom"))
async def mood_selected(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not await check_pro(user_id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    mood = call.data.replace("mood_", "")

    await call.message.edit_caption(
        caption=f"🔍 <b>{mood.capitalize()}</b> kayfiyatga mos kontentlar qidirilmoqda...",
        parse_mode="HTML"
    )

    async with AsyncSessionLocal() as session:
        recs = await get_recommendations(
            session, user_id,
            target_moods=[mood],
            limit=6,
            is_pro=True
        )

    if not recs:
        return await call.message.edit_caption(
            caption="😕 Bu kayfiyatga mos kontent topilmadi.",
            parse_mode="HTML"
        )

    # Birinchi kontent
    item = recs[0]
    mood_labels = {
        "sad": "😢 G'amgin", "romantic": "💕 Romantik", "dark": "🌑 Dark",
        "motivational": "💪 Motivatsion", "action": "⚔️ Jangari",
        "funny": "😂 Kulgili", "mystery": "🔍 Sirli", "chill": "🌸 Chill",
        "fantasy": "🧙 Fantastik", "scary": "😱 Qo'rqinchli",
    }
    mood_label = mood_labels.get(mood, mood.capitalize())

    text = (
        f"{mood_label} <b>Kayfiyatga Mos</b>\n\n"
        f"{format_content_card(item)}\n\n"
        f"📖 {(item.get('description') or '')[:150]}..."
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="▶️ Ko'rish", callback_data=f"watch_{item['id']}"))
    if len(recs) > 1:
        kb.row(InlineKeyboardButton(
            text=f"⏭ Keyingi ({len(recs)-1} ta bor)",
            callback_data=f"mood_next_{mood}_1"
        ))
    kb.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="pro_mood"))

    poster = item.get("poster_file_id") or item.get("inline_thumbnail_url")
    try:
        if poster:
            await call.message.edit_media(
                types.InputMediaPhoto(media=poster, caption=text, parse_mode="HTML"),
                reply_markup=kb.as_markup()
            )
        else:
            await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()


@pro_user_router.callback_query(F.data.startswith("mood_next_"))
async def mood_next(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not await check_pro(user_id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    # format: mood_next_{mood}_{idx}
    parts = call.data.replace("mood_next_", "").rsplit("_", 1)
    mood  = parts[0]
    idx   = int(parts[1])

    async with AsyncSessionLocal() as session:
        recs = await get_recommendations(session, user_id, target_moods=[mood], limit=6, is_pro=True)

    if idx >= len(recs):
        return await call.answer("🔚 Tugadi!", show_alert=True)

    item = recs[idx]
    text = (
        f"😌 <b>Mood: {mood.capitalize()}</b> ({idx+1}/{len(recs)})\n\n"
        f"{format_content_card(item)}\n\n"
        f"📖 {(item.get('description') or '')[:150]}..."
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="▶️ Ko'rish", callback_data=f"watch_{item['id']}"))
    if idx + 1 < len(recs):
        kb.row(InlineKeyboardButton(text="⏭ Keyingi", callback_data=f"mood_next_{mood}_{idx+1}"))
    kb.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="pro_mood"))

    poster = item.get("poster_file_id") or item.get("inline_thumbnail_url")
    try:
        if poster:
            await call.message.edit_media(
                types.InputMediaPhoto(media=poster, caption=text, parse_mode="HTML"),
                reply_markup=kb.as_markup()
            )
        else:
            await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  TRENDING / TOP / RISING / HIDDEN GEMS
# ═══════════════════════════════════════════════════════════

async def _show_list(
    call: types.CallbackQuery,
    items: list[dict],
    title: str,
    back_cb: str = "kawaii_pass"
):
    """Ro'yxat ko'rsatish uchun universal funksiya."""
    if not items:
        return await call.message.edit_caption(
            caption=f"{title}\n\n😕 Hozircha ma'lumot yo'q.",
            parse_mode="HTML"
        )

    # Inline keyboard - har bir kontent uchun
    kb = InlineKeyboardBuilder()
    text = f"{title}\n\n"
    for i, item in enumerate(items[:6], 1):
        genres = ", ".join(item.get("genres", [])[:2]) or "—"
        locked = "🔒 " if item.get("locked") else ""
        text += f"{i}. {locked}<b>{item['title']}</b> ({item.get('year', '—')})\n"
        text += f"   ⭐{item.get('rating', 0):.1f} | 🎭{genres}\n\n"
        if not item.get("locked"):
            kb.row(InlineKeyboardButton(
                text=f"{'🔒' if item.get('locked') else '▶️'} {item['title'][:25]}",
                callback_data=f"watch_{item['id']}"
            ))
        else:
            kb.row(InlineKeyboardButton(
                text=f"🔒 {item['title'][:25]}",
                callback_data="pro_upgrade_hint"
            ))

    kb.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data=back_cb))

    try:
        await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()


@pro_user_router.callback_query(F.data == "pro_trending")
async def pro_trending(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)
    async with AsyncSessionLocal() as session:
        items = await get_trending(session, limit=6, is_pro=True)
    await _show_list(call, items, "🔥 <b>Trending — Bu hafta eng ko'p ko'rilganlar</b>")


@pro_user_router.callback_query(F.data == "pro_top")
async def pro_top(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)
    async with AsyncSessionLocal() as session:
        items = await get_top_rated(session, limit=6, is_pro=True)
    await _show_list(call, items, "⭐ <b>Top Reyting — Eng yuqori baholangan</b>")


@pro_user_router.callback_query(F.data == "pro_rising")
async def pro_rising(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)
    async with AsyncSessionLocal() as session:
        items = await get_rising(session, limit=6, is_pro=True)
    await _show_list(call, items, "📈 <b>Rising — Tez o'sayotgan kontentlar</b>")


@pro_user_router.callback_query(F.data == "pro_hidden")
async def pro_hidden_gems(call: types.CallbackQuery):
    if not await check_pro(call.from_user.id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)
    async with AsyncSessionLocal() as session:
        items = await get_hidden_gems(session, limit=6)
    await _show_list(call, items, "💎 <b>Hidden Gems — Kam mashhur, lekin oltin!</b>")


# ═══════════════════════════════════════════════════════════
#  RELATED CONTENT
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data.startswith("related_"))
async def show_related(call: types.CallbackQuery):
    anime_id = int(call.data.replace("related_", ""))
    is_pro   = await check_pro(call.from_user.id)

    async with AsyncSessionLocal() as session:
        items = await get_related_content(session, anime_id, limit=5, is_pro=is_pro)
        anime = await session.get(Anime, anime_id)

    if not items:
        return await call.answer("😕 O'xshash kontent topilmadi.", show_alert=True)

    title = anime.title if anime else "Bu kontent"
    await _show_list(call, items, f"🔗 <b>{title}</b> bilan o'xshashlar", back_cb="kawaii_pass")


# ═══════════════════════════════════════════════════════════
#  SMART CONTINUE
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data == "pro_continue")
async def pro_smart_continue(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not await check_pro(user_id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    async with AsyncSessionLocal() as session:
        items = await get_smart_continue(session, user_id)

    if not items:
        return await call.message.edit_caption(
            caption=(
                "▶️ <b>Smart Continue</b>\n\n"
                "Hozircha davom ettiriladigan kontent yo'q.\n"
                "Biror nima ko'rishni boshlang! 😊"
            ),
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="↩️ Orqaga", callback_data="kawaii_pass")
            ).as_markup(),
            parse_mode="HTML"
        )

    text = "▶️ <b>Smart Continue — Qolgan joydan davom eting</b>\n\n"
    kb   = InlineKeyboardBuilder()

    for item in items:
        ep_info = f"{item.get('resume_from', 1)}-qism"
        text += f"🎬 <b>{item['title']}</b>\n"
        text += f"   ▶️ {ep_info} dan davom etish\n\n"
        kb.row(InlineKeyboardButton(
            text=f"▶️ {item['title'][:20]} — {ep_info}",
            callback_data=f"watch_ep_{item['id']}_{item.get('resume_from', 1)}"
        ))

    kb.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="kawaii_pass"))

    try:
        await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  TASTE PROFILE
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data == "pro_taste")
async def pro_taste_profile(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not await check_pro(user_id):
        return await call.answer("🔒 Pro kerak!", show_alert=True)

    async with AsyncSessionLocal() as session:
        profile = await get_or_create_taste_profile(session, user_id)

    identity = build_identity_label(profile)

    # Top 3 genre
    genres = dict(profile.fav_genres or {})
    top_genres = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:3]
    genres_text = "\n".join(f"  • {g}: {c} marta" for g, c in top_genres) or "  Hali ma'lumot yo'q"

    # Top 3 tag
    tags = dict(profile.fav_tags or {})
    top_tags = sorted(tags.items(), key=lambda x: x[1], reverse=True)[:3]
    tags_text = "\n".join(f"  • {t}: {c} marta" for t, c in top_tags) or "  Hali ma'lumot yo'q"

    # Top mood
    moods = dict(profile.fav_moods or {})
    top_moods = sorted(moods.items(), key=lambda x: x[1], reverse=True)[:2]
    moods_text = ", ".join(m for m, _ in top_moods) or "Aniqlanmagan"

    type_labels = {"anime": "🎌 Anime", "movie": "🎥 Kino", "serial": "📺 Serial", "dorama": "🌸 Dorama"}
    fav_type = type_labels.get(profile.fav_type or "anime", "🎌 Anime")

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🤖 Menga mos tavsiyalar", callback_data="pro_recommend"),
        InlineKeyboardButton(text="↩️ Orqaga", callback_data="kawaii_pass"),
    )

    await call.message.edit_caption(
        caption=(
            f"👤 <b>Sizning Did Profilingiz</b>\n\n"
            f"🎯 <b>{identity}</b>\n\n"
            f"🎭 <b>Sevimli janrlar:</b>\n{genres_text}\n\n"
            f"🏷 <b>Sevimli teglar:</b>\n{tags_text}\n\n"
            f"😌 <b>Sevimli mood:</b> {moods_text}\n"
            f"📁 <b>Sevimli tur:</b> {fav_type}\n\n"
            f"<i>Bu ma'lumotlar siz ko'rgan kontentlar asosida yig'iladi.</i>"
        ),
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  NEXT RECOMMENDATION HOOK
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data.startswith("finished_"))
async def content_finished(call: types.CallbackQuery):
    """
    User kontent tugaganda chaqiriladi.
    Callback: finished_{anime_id}
    """
    user_id  = call.from_user.id
    anime_id = int(call.data.replace("finished_", ""))
    is_pro   = await check_pro(user_id)

    async with AsyncSessionLocal() as session:
        # Tugagan deb belgilash
        await add_to_watch_history(session, user_id, anime_id, is_completed=True)

        if is_pro:
            next_item = await get_next_recommendation(session, user_id, anime_id, is_pro=True)
        else:
            next_item = None

    if next_item and is_pro:
        reason_map = {
            "sequel":      "➡️ Davomi:",
            "personalized": "🤖 Sizga mos:",
        }
        reason_label = reason_map.get(next_item.get("reason", ""), "🎬")

        text = (
            f"✅ Tugadi! Keyingi kontent:\n\n"
            f"{reason_label}\n"
            f"{format_content_card(next_item)}"
        )
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(
            text="▶️ Ko'rish",
            callback_data=f"watch_{next_item['id']}"
        ))
        kb.row(InlineKeyboardButton(
            text="🤖 Ko'proq tavsiyalar",
            callback_data="pro_recommend"
        ))
        await call.answer(f"✅ Tugadi! Keyingi tavsiya tayyor.", show_alert=False)
        try:
            await call.message.edit_caption(
                caption=text, reply_markup=kb.as_markup(), parse_mode="HTML"
            )
        except Exception:
            await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await call.answer("✅ Kontent tugadi! Yangi tavsiyalar uchun Pro bo'ling.", show_alert=True)


# ═══════════════════════════════════════════════════════════
#  VIEW RECORDING (mavjud watch_ handlerga qo'shimcha)
# ═══════════════════════════════════════════════════════════

@pro_user_router.callback_query(F.data.startswith("watch_ep_"))
async def watch_from_episode(call: types.CallbackQuery):
    """Smart Continue — belgilangan qismdan ko'rish."""
    parts    = call.data.replace("watch_ep_", "").split("_")
    anime_id = int(parts[0])
    episode  = int(parts[1]) if len(parts) > 1 else 1
    user_id  = call.from_user.id

    async with AsyncSessionLocal() as session:
        await record_view(session, anime_id, user_id)
        await add_to_watch_history(session, user_id, anime_id, episode=episode)

    # Mavjud watch_ handlerga yo'naltirish
    await call.data  # Mavjud handlers/users.py dagi watch_ handler ishlaydi
    # Oddiy: call.data ni watch_{anime_id} ga o'zgartirish kerak
    # Bu qismni mavjud watch callback bilan bog'lash zarur
    await call.answer(f"▶️ {episode}-qismdan boshlanmoqda...", show_alert=True)


@pro_user_router.callback_query(F.data == "pro_upgrade_hint")
async def pro_upgrade_hint(call: types.CallbackQuery):
    await call.answer(
        "🔒 Bu kontent Kaworai Pro uchun!\n"
        "Pro bo'lish uchun @admin bilan bog'laning.",
        show_alert=True
    )