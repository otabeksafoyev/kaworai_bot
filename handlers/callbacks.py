from aiogram import Router, F, types
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaVideo
)
from sqlalchemy import select, func

from database.models import Anime, Series, AnimeRating
from database.engine import AsyncSessionLocal
from database.queries import get_user_rating, add_or_update_rating

callback_router = Router()

BOT_USERNAME = "kaworai_uz_bot"  # ✅ bot username sini shu yerda o'zgartiring
PAGE_SIZE = 12


def episodes_page_keyboard(anime_id: int, episodes: list, page: int = 0) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_episodes = episodes[start:end]
    total_pages = (len(episodes) - 1) // PAGE_SIZE

    buttons = []
    row = []
    for ep in page_episodes:
        row.append(InlineKeyboardButton(
            text=f"◉ {ep.episode}",
            callback_data=f"ep_{anime_id}_{ep.episode}"
        ))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"eppage_{anime_id}_{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"eppage_{anime_id}_{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"anime_info_{anime_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def player_keyboard(
    anime_id: int,
    episode: int,
    total: int,
    is_last: bool = False,
    user_rated: bool = False
) -> InlineKeyboardMarkup:
    """Rasmdagidek: Oldingi | [◉:N] | Keyingi, Qismlar, Ulashish, Kaworai Pro, Menu, Muammo"""
    buttons = []

    # ✅ Sahifa ko'rsatgich + navigatsiya
    nav = []
    if episode > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"ep_{anime_id}_{episode - 1}"))
    nav.append(InlineKeyboardButton(text=f"[◉ :{episode}]", callback_data=f"episodes_{anime_id}"))
    if episode < total:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"ep_{anime_id}_{episode + 1}"))
    buttons.append(nav)

    # ✅ Ulashish tugmasi — https://t.me/BOT?start=anime_ID formatida
    buttons.append([
        InlineKeyboardButton(
            text="🔗 Ulashish",
            switch_inline_query=f"anime_{anime_id}"
        )
    ])

    # ✅ Kaworai Pro
    buttons.append([
        InlineKeyboardButton(text="🟢 Kaworai Pro", callback_data="kawaii_pass")
    ])

    # ✅ Menu va Muammo
    buttons.append([
        InlineKeyboardButton(text="🏠 Menu", callback_data="main_menu"),
        InlineKeyboardButton(text="⚠️ Muammo", callback_data="report_problem")
    ])

    # Baho berish
    if is_last and not user_rated:
        buttons.append([InlineKeyboardButton(text="⭐ Baho berish", callback_data=f"rate_{anime_id}")])
    elif is_last and user_rated:
        buttons.append([InlineKeyboardButton(text="✅ Baho berilgan", callback_data=f"rated_{anime_id}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ====================== ANIME INFO ======================

@callback_router.callback_query(F.data.startswith("anime_info_"))
async def show_anime_info(call: CallbackQuery):
    anime_id = int(call.data.replace("anime_info_", ""))
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Anime topilmadi!", show_alert=True)
        ep_count = await session.scalar(select(func.count(Series.id)).where(Series.anime_id == anime_id))

    genres_text = ", ".join(anime.genres) if anime.genres else "Nomalum"
    total_ep_text = str(anime.total_episodes) if anime.total_episodes else "?"

    caption = (
        f"🎬 <b>{anime.title}</b>\n\n"
        f"📅 Yil: {anime.year}\n"
        f"🎭 Janr: {genres_text}\n"
        f"⭐ Reyting: {anime.rating} ({anime.rating_count} ovoz)\n"
        f"📺 Qismlar: {ep_count}/{total_ep_text}\n\n"
        f"📖 {anime.description}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Ko'rish", callback_data=f"watch_{anime_id}")],
        [InlineKeyboardButton(text="🏠 Asosiy", callback_data="main_menu")]
    ])

    try:
        await call.message.edit_caption(caption=caption, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# ====================== WATCH — inline dan kelganda 1-qismni chiqaradi ======================

@callback_router.callback_query(F.data.startswith("watch_"))
async def watch_anime(call: CallbackQuery):
    anime_id = int(call.data.split("_")[1])
    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Anime topilmadi!", show_alert=True)

        result = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc())
        )
        episodes = result.scalars().all()
        user_rating = await get_user_rating(session, anime_id, user_id)

    if not episodes:
        return await call.answer("❌ Hali qismlar qo'shilmagan!", show_alert=True)

    first_ep = episodes[0]
    total = len(episodes)
    is_last = (total == 1)
    user_rated = user_rating is not None
    total_ep_text = str(anime.total_episodes) if anime.total_episodes else str(total)

    kb = player_keyboard(anime_id, first_ep.episode, total, is_last, user_rated)

    await call.message.answer_video(
        video=first_ep.file_id,
        caption=(
            f"🎬 <b>{anime.title}</b>\n"
            f"🖼 Qism: {first_ep.episode} | "
            f"📺 Jami: {total_ep_text} qism"
        ),
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


# ====================== EPISODE — edit_message_media bilan video almashtiriladi ======================

@callback_router.callback_query(F.data.startswith("ep_"))
async def show_episode(call: CallbackQuery):
    parts = call.data.split("_")
    anime_id = int(parts[1])
    episode = int(parts[2])
    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        result = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc())
        )
        episodes = result.scalars().all()
        user_rating = await get_user_rating(session, anime_id, user_id)

    if not episodes:
        return await call.answer("❌ Qismlar topilmadi!", show_alert=True)

    ep = next((e for e in episodes if e.episode == episode), None)
    if not ep:
        return await call.answer("❌ Bu qism topilmadi!", show_alert=True)

    total = len(episodes)
    max_ep = max(e.episode for e in episodes)
    is_last = (episode == max_ep)
    user_rated = user_rating is not None
    total_ep_text = str(anime.total_episodes) if anime.total_episodes else str(total)

    kb = player_keyboard(anime_id, episode, total, is_last, user_rated)

    caption = (
        f"🎬 <b>{anime.title}</b>\n"
        f"🖼 Qism: {episode} | "
        f"📺 Jami: {total_ep_text} qism"
    )

    # ✅ Agar xabar video bo'lsa — edit_message_media bilan almashtir (yangi xabar EMAS)
    try:
        await call.message.edit_media(
            media=InputMediaVideo(media=ep.file_id, caption=caption, parse_mode="HTML"),
            reply_markup=kb
        )
    except Exception:
        # Agar edit bo'lmasa (masalan, boshqa turdagi xabar) — yangi xabar yuboramiz
        await call.message.answer_video(
            video=ep.file_id,
            caption=caption,
            reply_markup=kb,
            parse_mode="HTML"
        )
    await call.answer()


# ====================== EPISODES LIST ======================

@callback_router.callback_query(F.data.startswith("episodes_"))
async def show_episodes_list(call: CallbackQuery):
    anime_id = int(call.data.split("_")[1])

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        result = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc())
        )
        episodes = result.scalars().all()

    if not episodes:
        return await call.answer("❌ Qismlar yo'q!", show_alert=True)

    total_ep_text = str(anime.total_episodes) if anime.total_episodes else str(len(episodes))
    kb = episodes_page_keyboard(anime_id, episodes, page=0)
    text = (
        f"🎬 <b>{anime.title}</b>\n"
        f"📺 {len(episodes)}/{total_ep_text} qism — birini tanlang:"
    )

    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# ====================== EPISODES PAGE ======================

@callback_router.callback_query(F.data.startswith("eppage_"))
async def episodes_page(call: CallbackQuery):
    parts = call.data.split("_")
    anime_id = int(parts[1])
    page = int(parts[2])

    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        result = await session.execute(
            select(Series).where(Series.anime_id == anime_id).order_by(Series.episode.asc())
        )
        episodes = result.scalars().all()

    total_ep_text = str(anime.total_episodes) if anime.total_episodes else str(len(episodes))
    kb = episodes_page_keyboard(anime_id, episodes, page=page)
    text = (
        f"🎬 <b>{anime.title}</b>\n"
        f"📺 {len(episodes)}/{total_ep_text} qism — birini tanlang:\n"
        f"📄 Sahifa: {page + 1}"
    )
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# ====================== RATING ======================

@callback_router.callback_query(F.data.startswith("rate_"))
async def rate_anime(call: CallbackQuery):
    anime_id = int(call.data.split("_")[1])
    async with AsyncSessionLocal() as session:
        user_rating = await get_user_rating(session, anime_id, call.from_user.id)
    if user_rating:
        return await call.answer("✅ Siz allaqachon baho bergansiz!", show_alert=True)

    buttons = []
    row = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f"score_{anime_id}_{i}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"episodes_{anime_id}")])

    await call.message.answer(
        "⭐ <b>Anime uchun baho bering (1-10):</b>\n\n1 — Yomon | 5 — O'rtacha | 10 — A'lo",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await call.answer()


@callback_router.callback_query(F.data.startswith("score_"))
async def save_score(call: CallbackQuery):
    parts = call.data.split("_")
    anime_id = int(parts[1])
    score = int(parts[2])

    async with AsyncSessionLocal() as session:
        existing = await get_user_rating(session, anime_id, call.from_user.id)
        if existing:
            return await call.answer("✅ Siz allaqachon baho bergansiz!", show_alert=True)
        new_avg = await add_or_update_rating(session, anime_id, call.from_user.id, score)
        anime = await session.get(Anime, anime_id)

    stars = "⭐" * score
    await call.message.edit_text(
        f"✅ <b>Bahoyingiz qabul qilindi!</b>\n\n"
        f"🎬 Anime: <b>{anime.title if anime else anime_id}</b>\n"
        f"⭐ Sizning bahoyingiz: <b>{score}/10</b> {stars}\n"
        f"📊 O'rtacha reyting: <b>{new_avg}/10</b>",
        parse_mode="HTML"
    )
    await call.answer(f"⭐ {score}/10 — Rahmat!", show_alert=True)


@callback_router.callback_query(F.data.startswith("rated_"))
async def already_rated(call: CallbackQuery):
    await call.answer("✅ Siz allaqachon baho bergansiz!", show_alert=True)


# ====================== MAIN MENU ======================

@callback_router.callback_query(F.data == "main_menu")
async def back_to_main(call: CallbackQuery):
    from handlers.users import send_main_menu
    try:
        await call.message.delete()
    except Exception:
        pass
    await send_main_menu(call.message)
    await call.answer()


@callback_router.callback_query(F.data == "show_genres")
async def show_genres_callback(call: CallbackQuery):
    await call.answer("🚧 Tez kunda!", show_alert=True)


@callback_router.callback_query(F.data == "no_episodes")
async def no_episodes_cb(call: CallbackQuery):
    await call.answer("⏳ Qismlar hali qo'shilmagan!", show_alert=True)


@callback_router.callback_query(F.data == "report_problem")
async def report_problem_cb(call: CallbackQuery):
    await call.answer("⚠️ Muammo haqida adminlarga xabar yuborildi!", show_alert=True)


@callback_router.callback_query(F.data == "kawaii_pass")
async def kawaii_pass_cb(call: CallbackQuery):
    await call.answer("🟢 Kaworai Pro tez kunda ishga tushadi!", show_alert=True)