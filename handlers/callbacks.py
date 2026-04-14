import asyncio
from aiogram import Router, F, types
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, InputMediaPhoto, InputMediaVideo
)
from sqlalchemy import select, func
from database.models import Anime, Series, AnimeRating, User, AnimeSubscription
from database.engine import AsyncSessionLocal
from database.queries import (
    get_user_rating, add_or_update_rating,
    subscribe_anime, unsubscribe_anime, is_subscribed_anime,
    add_to_watch_history, record_view,
)
from datetime import datetime
import os

callback_router = Router()

BOT_USERNAME = os.getenv("BOT_USERNAME", "kaworai_uz_bot")

# Qismlar bir sahifada ko'rsatiladi — sahifalash yo'q
# Barcha qismlar bir marta chiqadi, 4 ta button qatorida


# ── Pro tekshirish ───────────────────────────────────────────
async def _is_pro(user_id: int) -> bool:
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


# ── Caption ──────────────────────────────────────────────────
def _anime_caption(anime: Anime) -> str:
    type_emoji  = {"anime": "🎌", "movie": "🎥", "serial": "📺", "dorama": "🌸"}
    emoji       = type_emoji.get(getattr(anime, "content_type", None) or "anime", "🎬")
    genres_text = ", ".join(anime.genres or []) or "Nomalum"
    tags        = getattr(anime, "tags", None) or []
    tags_text   = ", ".join(tags[:3])
    lock_str    = " 🔒 Pro" if getattr(anime, "is_pro_locked", False) else ""

    status_map  = {
        "completed": "✅ Tugagan",
        "ongoing":   "📡 Davom etmoqda",
        "announced": "📢 Kutilmoqda",
    }
    status_str  = status_map.get(getattr(anime, "status", "") or "", "")

    cap = (
        f"{emoji} <b>{anime.title}</b>"
        + (f" ({anime.year})" if anime.year else "")
        + lock_str + "\n\n"
        f"🎭 {genres_text}\n"
        + (f"🏷 {tags_text}\n" if tags_text else "")
        + f"⭐ {anime.rating:.1f} ({anime.rating_count} ovoz)\n"
        + (f"📊 {status_str}\n" if status_str else "")
        + f"🆔 Kod: <code>{anime.id}</code>\n\n"
        f"📖 {(anime.description or '')[:300]}"
    )
    return cap


def _share_url(anime_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=anime_{anime_id}"


# ── Anime info klaviaturasi ──────────────────────────────────
def _anime_info_kb(
    anime_id: int,
    has_episodes: bool,
    subscribed: bool,
    is_pro: bool,
    is_pro_locked: bool,
) -> InlineKeyboardMarkup:
    rows = []

    if is_pro_locked and not is_pro:
        rows.append([InlineKeyboardButton(
            text="🔒 Faqat Kaworai Pro uchun",
            callback_data="kawaii_pass"
        )])
    elif has_episodes:
        rows.append([InlineKeyboardButton(
            text="▶️ 1-qismdan tomosha qilish",
            callback_data=f"watch_start_{anime_id}"
        )])
        rows.append([InlineKeyboardButton(
            text="📋 Qismlar ro'yxati",
            callback_data=f"episodes_{anime_id}"
        )])
    else:
        rows.append([InlineKeyboardButton(
            text="⏳ Qismlar hali qo'shilmagan",
            callback_data="no_episodes"
        )])

    sub_icon = "🔔" if subscribed else "🔕"
    sub_txt  = "Obunani bekor qilish" if subscribed else "🔔 Obuna bo'lish"
    rows.append([InlineKeyboardButton(
        text=f"{sub_icon} {sub_txt}",
        callback_data=f"toggle_sub_{anime_id}"
    )])

    # Ulashish — url button: chat ochiladi va link yuboriladi
    rows.append([InlineKeyboardButton(
        text="🔗 Ulashish",
        url=f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}%3Fstart%3Danime_{anime_id}"
    )])

    rows.append([InlineKeyboardButton(
        text="🏠 Asosiy menyu", callback_data="main_menu"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Player klaviaturasi ──────────────────────────────────────
def _player_kb(
    anime_id: int,
    episode: int,
    total_eps: int,
    max_ep: int,
    is_last: bool,
    user_rated: bool,
    subscribed: bool,
    is_pro: bool,
) -> InlineKeyboardMarkup:
    rows = []

    # Navigatsiya
    nav = []
    if episode > 1:
        nav.append(InlineKeyboardButton(
            text="⬅️ Oldingi",
            callback_data=f"ep_{anime_id}_{episode - 1}"
        ))
    if episode < max_ep:
        nav.append(InlineKeyboardButton(
            text="Keyingi ➡️",
            callback_data=f"ep_{anime_id}_{episode + 1}"
        ))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton(text="📋 Qismlar", callback_data=f"episodes_{anime_id}"),
        InlineKeyboardButton(text="🏠 Asosiy",  callback_data="main_menu"),
    ])

    # Muammolar
    rows.append([InlineKeyboardButton(
        text="⚠️ Muammo bormi?",
        callback_data=f"problems_{anime_id}_{episode}"
    )])

    # Obuna
    sub_icon = "🔔" if subscribed else "🔕"
    sub_txt  = "Obunani bekor qilish" if subscribed else "🔔 Obuna bo'lish"
    rows.append([InlineKeyboardButton(
        text=f"{sub_icon} {sub_txt}",
        callback_data=f"toggle_sub_{anime_id}"
    )])

    # Ulashish — url button: chat ochiladi va link yuboriladi
    rows.append([InlineKeyboardButton(
        text="🔗 Ulashish",
        url=f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}%3Fstart%3Danime_{anime_id}"
    )])

    # Baho
    if is_last and not user_rated:
        rows.append([InlineKeyboardButton(
            text="⭐ Baho berish", callback_data=f"rate_{anime_id}"
        )])
    elif is_last and user_rated:
        rows.append([InlineKeyboardButton(
            text="✅ Baho berilgan", callback_data=f"rated_{anime_id}"
        )])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Qismlar ro'yxati — barcha qismlar bir marta ──────────────
def _episodes_kb(anime_id: int, episodes: list) -> InlineKeyboardMarkup:
    """
    Barcha qismlar bir marta chiqadi.
    4 ta button bir qatorda.
    Sahifalash yo'q.
    """
    rows = []
    row  = []
    for ep in sorted(episodes, key=lambda e: e.episode):
        row.append(InlineKeyboardButton(
            text=str(ep.episode),
            callback_data=f"ep_{anime_id}_{ep.episode}"
        ))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        text="🔙 Orqaga", callback_data=f"anime_info_{anime_id}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════════════════════════════════════════════════
#  ANIME INFO
# ═══════════════════════════════════════════════════════════

@callback_router.callback_query(F.data.startswith("anime_info_"))
async def show_anime_info(call: CallbackQuery):
    anime_id = int(call.data.replace("anime_info_", ""))
    user_id  = call.from_user.id
    is_pro   = await _is_pro(user_id)

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Anime topilmadi!", show_alert=True)

        if getattr(anime, "is_pro_locked", False) and not is_pro:
            return await call.answer(
                "🔒 Bu kontent faqat Kaworai Pro uchun!\n"
                "Pro olish uchun 🟢 Kaworai Pro tugmasini bosing.",
                show_alert=True
            )

        ep_count = (await session.execute(
            select(func.count(Series.id)).where(Series.anime_id == anime_id)
        )).scalar() or 0

        subscribed = await is_subscribed_anime(session, anime_id, user_id)

    caption = _anime_caption(anime)
    kb = _anime_info_kb(
        anime_id, ep_count > 0, subscribed, is_pro,
        getattr(anime, "is_pro_locked", False)
    )

    try:
        if anime.poster_file_id:
            await call.message.edit_media(
                InputMediaPhoto(media=anime.poster_file_id, caption=caption, parse_mode="HTML"),
                reply_markup=kb
            )
        else:
            await call.message.edit_caption(caption=caption, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await call.message.edit_text(caption, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await call.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  WATCH START
# ═══════════════════════════════════════════════════════════

@callback_router.callback_query(F.data.startswith("watch_start_"))
async def watch_start(call: CallbackQuery):
    anime_id = int(call.data.replace("watch_start_", ""))
    user_id  = call.from_user.id
    is_pro   = await _is_pro(user_id)

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Topilmadi!", show_alert=True)
        if getattr(anime, "is_pro_locked", False) and not is_pro:
            return await call.answer("🔒 Faqat Pro uchun!", show_alert=True)

        result = await session.execute(
            select(Series)
            .where(Series.anime_id == anime_id)
            .order_by(Series.episode.asc())
        )
        episodes    = result.scalars().all()
        user_rating = await get_user_rating(session, anime_id, user_id)
        subscribed  = await is_subscribed_anime(session, anime_id, user_id)

    if not episodes:
        return await call.answer("❌ Hali qismlar qo'shilmagan!", show_alert=True)

    ep         = episodes[0]
    total      = len(episodes)
    max_ep     = max(e.episode for e in episodes)
    is_last    = (ep.episode == max_ep)
    user_rated = user_rating is not None

    kb = _player_kb(anime_id, ep.episode, total, max_ep, is_last, user_rated, subscribed, is_pro)
    caption = (
        f"🎬 <b>{anime.title}</b>\n"
        f"▶️ {ep.episode}-qism  |  📺 Jami: {total} qism"
    )

    async with AsyncSessionLocal() as session:
        await add_to_watch_history(session, user_id, anime_id, ep.episode)
        await record_view(session, anime_id, user_id)

    # Pro → xabar saqlanib qoladi (o'chirilmaydi)
    # Oddiy → yangi xabar, avvalgisi o'chib ketadi
    if is_pro:
        # Pro: edit_media bilan xabar o'zgartirish (o'chirmaydi)
        try:
            await call.message.edit_media(
                InputMediaVideo(media=ep.file_id, caption=caption, parse_mode="HTML"),
                reply_markup=kb
            )
        except Exception:
            await call.message.answer_video(
                video=ep.file_id, caption=caption,
                reply_markup=kb, parse_mode="HTML"
            )
    else:
        # Oddiy: xabarni protect_content bilan yuborish (yuklab olish, forward mumkin emas)
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer_video(
            video=ep.file_id, caption=caption,
            reply_markup=kb, parse_mode="HTML",
            protect_content=True   # ← copy/forward/download bloklanadi
        )
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  EPISODE — navigatsiya
# ═══════════════════════════════════════════════════════════

@callback_router.callback_query(F.data.startswith("ep_"))
async def show_episode(call: CallbackQuery):
    parts    = call.data.split("_")
    anime_id = int(parts[1])
    ep_str   = parts[2]

    if ep_str == "cancel":
        return await call.answer()

    episode = int(ep_str)
    user_id = call.from_user.id
    is_pro  = await _is_pro(user_id)

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Topilmadi!", show_alert=True)
        if getattr(anime, "is_pro_locked", False) and not is_pro:
            return await call.answer("🔒 Faqat Pro uchun!", show_alert=True)

        result = await session.execute(
            select(Series)
            .where(Series.anime_id == anime_id)
            .order_by(Series.episode.asc())
        )
        episodes    = result.scalars().all()
        user_rating = await get_user_rating(session, anime_id, user_id)
        subscribed  = await is_subscribed_anime(session, anime_id, user_id)

    ep = next((e for e in episodes if e.episode == episode), None)
    if not ep:
        return await call.answer("❌ Bu qism topilmadi!", show_alert=True)

    total      = len(episodes)
    max_ep     = max(e.episode for e in episodes)
    is_last    = (episode == max_ep)
    user_rated = user_rating is not None

    kb      = _player_kb(anime_id, episode, total, max_ep, is_last, user_rated, subscribed, is_pro)
    caption = (
        f"🎬 <b>{anime.title}</b>\n"
        f"▶️ {episode}-qism  |  📺 Jami: {total} qism"
    )

    async with AsyncSessionLocal() as session:
        await add_to_watch_history(
            session, user_id, anime_id, episode,
            is_completed=(episode == max_ep)
        )

    if is_pro:
        # Pro: xabar o'zgartiriladi (o'chirmaydi)
        try:
            await call.message.edit_media(
                InputMediaVideo(media=ep.file_id, caption=caption, parse_mode="HTML"),
                reply_markup=kb
            )
        except Exception:
            await call.message.answer_video(
                video=ep.file_id, caption=caption,
                reply_markup=kb, parse_mode="HTML"
            )
    else:
        # Oddiy: avvalgisini o'chir, yangi protect_content bilan yuborish
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer_video(
            video=ep.file_id, caption=caption,
            reply_markup=kb, parse_mode="HTML",
            protect_content=True
        )
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  EPISODES LIST — barcha qismlar bir marta
# ═══════════════════════════════════════════════════════════

@callback_router.callback_query(F.data.startswith("episodes_"))
async def show_episodes_list(call: CallbackQuery):
    anime_id = int(call.data.split("_")[1])
    is_pro   = await _is_pro(call.from_user.id)

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Topilmadi!", show_alert=True)
        if getattr(anime, "is_pro_locked", False) and not is_pro:
            return await call.answer("🔒 Faqat Pro uchun!", show_alert=True)

        result = await session.execute(
            select(Series)
            .where(Series.anime_id == anime_id)
            .order_by(Series.episode.asc())
        )
        episodes = result.scalars().all()

    if not episodes:
        return await call.answer("❌ Qismlar yo'q!", show_alert=True)

    # Barcha qismlar bir marta — sahifalash yo'q
    kb   = _episodes_kb(anime_id, episodes)
    text = (
        f"🎬 <b>{anime.title}</b>\n"
        f"📺 Jami {len(episodes)} qism — birini tanlang:"
    )
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  OBUNA TOGGLE
# ═══════════════════════════════════════════════════════════

@callback_router.callback_query(F.data.startswith("toggle_sub_"))
async def toggle_subscription(call: CallbackQuery):
    anime_id = int(call.data.replace("toggle_sub_", ""))
    user_id  = call.from_user.id

    async with AsyncSessionLocal() as session:
        already = await is_subscribed_anime(session, anime_id, user_id)
        if already:
            await unsubscribe_anime(session, anime_id, user_id)
            await call.answer("🔕 Obuna bekor qilindi!", show_alert=True)
        else:
            await subscribe_anime(session, anime_id, user_id)
            await call.answer(
                "🔔 Obuna bo'ldingiz!\nYangi qismlar chiqsa xabar beramiz.",
                show_alert=True
            )

    await show_anime_info(CallbackQuery(
        id=call.id,
        from_user=call.from_user,
        message=call.message,
        data=f"anime_info_{anime_id}",
        chat_instance=call.chat_instance
    ))


# ═══════════════════════════════════════════════════════════
#  MUAMMOLAR
# ═══════════════════════════════════════════════════════════

@callback_router.callback_query(F.data.startswith("problems_"))
async def show_problems_menu(call: CallbackQuery):
    parts    = call.data.split("_")
    anime_id = parts[1]
    episode  = parts[2]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔊 Ovoz tezlashib ketgan",
            callback_data=f"prob_speed_{anime_id}_{episode}"
        )],
        [InlineKeyboardButton(
            text="🔙 Orqaga",
            callback_data=f"ep_{anime_id}_{episode}"
        )],
    ])
    try:
        await call.message.edit_caption(
            caption="⚠️ <b>Epizodda muammo bormi?</b>\n\nPastdagi menyudan tanlang:",
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        await call.message.answer(
            "⚠️ <b>Epizodda muammo bormi?</b>\n\nPastdagi menyudan tanlang:",
            reply_markup=kb, parse_mode="HTML"
        )
    await call.answer()


@callback_router.callback_query(F.data.startswith("prob_speed_"))
async def problem_speed(call: CallbackQuery):
    parts    = call.data.split("_")
    anime_id = parts[2]
    episode  = parts[3]
    is_pro   = await _is_pro(call.from_user.id)

    text = (
        "🔊 <b>Ovoz tezlashib ketgan — yechim:</b>\n\n"
        "1️⃣ Telegramning <b>keshini tozalang:</b>\n"
        "   <i>Sozlamalar → Ma'lumotlar va saqlash → Keshni tozalash</i>\n\n"
        "2️⃣ Agar hal bo'lmasa, epizodni qurilmangizning "
        "<b>gallereyasiga saqlang</b> va o'sha yerdan tomosha qiling.\n\n"
        "✅ Bu 2 usul 90% holatlarda muammoni hal qiladi."
    )
    if not is_pro:
        text += (
            "\n\n━━━━━━━━━━━━━━━\n"
            "💎 <b>Kaworai Pro</b> obunasini sotib oling — "
            "sifatli va muammosiz tomosha qiling!"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🔙 Orqaga",
            callback_data=f"problems_{anime_id}_{episode}"
        )
    ]])
    try:
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# ═══════════════════════════════════════════════════════════
#  RATING
# ═══════════════════════════════════════════════════════════

@callback_router.callback_query(F.data.startswith("rate_"))
async def rate_anime(call: CallbackQuery):
    anime_id = int(call.data.split("_")[1])
    async with AsyncSessionLocal() as session:
        user_rating = await get_user_rating(session, anime_id, call.from_user.id)
    if user_rating:
        return await call.answer("✅ Siz allaqachon baho bergansiz!", show_alert=True)

    rows = []
    row  = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(
            text=str(i), callback_data=f"score_{anime_id}_{i}"
        ))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        text="❌ Bekor", callback_data=f"ep_{anime_id}_cancel"
    )])

    await call.message.answer(
        "⭐ <b>Baho bering (1-10):</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML"
    )
    await call.answer()


@callback_router.callback_query(F.data.startswith("score_"))
async def save_score(call: CallbackQuery):
    parts    = call.data.split("_")
    anime_id = int(parts[1])
    score    = int(parts[2])

    async with AsyncSessionLocal() as session:
        existing = await get_user_rating(session, anime_id, call.from_user.id)
        if existing:
            return await call.answer("✅ Allaqachon baho bergansiz!", show_alert=True)
        new_avg = await add_or_update_rating(session, anime_id, call.from_user.id, score)
        anime   = await session.get(Anime, anime_id)

    await call.message.edit_text(
        f"✅ <b>Baho qabul qilindi!</b>\n\n"
        f"🎬 <b>{anime.title if anime else anime_id}</b>\n"
        f"⭐ Sizning bahoyingiz: <b>{score}/10</b>\n"
        f"📊 O'rtacha: <b>{new_avg}/10</b>",
        parse_mode="HTML"
    )
    await call.answer(f"⭐ {score}/10 — Rahmat!", show_alert=True)


@callback_router.callback_query(F.data.startswith("rated_"))
async def already_rated(call: CallbackQuery):
    await call.answer("✅ Siz allaqachon baho bergansiz!", show_alert=True)


# ═══════════════════════════════════════════════════════════
#  MAIN MENU — avvalgi xabar o'chib, /start ga o'tadi
# ═══════════════════════════════════════════════════════════

@callback_router.callback_query(F.data == "main_menu")
async def back_to_main(call: CallbackQuery):
    from handlers.users import get_main_menu_keyboard, PHOTO_URL
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer_photo(
        photo=PHOTO_URL,
        caption="🎌 <b>Kaworai Anime Bot</b>",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML"
    )
    await call.answer()


@callback_router.callback_query(F.data == "no_episodes")
async def no_episodes_cb(call: CallbackQuery):
    await call.answer("⏳ Qismlar hali qo'shilmagan!", show_alert=True)


# ═══════════════════════════════════════════════════════════
#  WATCH (boshqa joylardan chaqirilgan)
# ═══════════════════════════════════════════════════════════

@callback_router.callback_query(
    F.data.startswith("watch_") & ~F.data.startswith("watch_start_")
)
async def watch_anime(call: CallbackQuery):
    raw      = call.data.replace("watch_", "")
    parts    = raw.split("_")
    anime_id = int(parts[0])
    ep_num   = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    user_id  = call.from_user.id
    is_pro   = await _is_pro(user_id)

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Topilmadi!", show_alert=True)
        if getattr(anime, "is_pro_locked", False) and not is_pro:
            return await call.answer("🔒 Faqat Pro uchun!", show_alert=True)

        result = await session.execute(
            select(Series)
            .where(Series.anime_id == anime_id)
            .order_by(Series.episode.asc())
        )
        episodes    = result.scalars().all()
        user_rating = await get_user_rating(session, anime_id, user_id)
        subscribed  = await is_subscribed_anime(session, anime_id, user_id)

    if not episodes:
        return await call.answer("❌ Hali qismlar qo'shilmagan!", show_alert=True)

    ep = next(
        (e for e in episodes if e.episode == ep_num), episodes[0]
    ) if ep_num else episodes[0]

    total      = len(episodes)
    max_ep     = max(e.episode for e in episodes)
    is_last    = (ep.episode == max_ep)
    user_rated = user_rating is not None

    kb      = _player_kb(anime_id, ep.episode, total, max_ep, is_last, user_rated, subscribed, is_pro)
    caption = (
        f"🎬 <b>{anime.title}</b>\n"
        f"▶️ {ep.episode}-qism  |  📺 Jami: {total} qism"
    )

    async with AsyncSessionLocal() as session:
        await add_to_watch_history(session, user_id, anime_id, ep.episode)

    if is_pro:
        try:
            await call.message.edit_media(
                InputMediaVideo(media=ep.file_id, caption=caption, parse_mode="HTML"),
                reply_markup=kb
            )
        except Exception:
            await call.message.answer_video(
                video=ep.file_id, caption=caption,
                reply_markup=kb, parse_mode="HTML"
            )
    else:
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer_video(
            video=ep.file_id, caption=caption,
            reply_markup=kb, parse_mode="HTML",
            protect_content=True
        )
    await call.answer()