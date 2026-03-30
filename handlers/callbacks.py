import asyncio
from aiogram import Router, F, types
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaVideo
from sqlalchemy import select, func
from database.models import Anime, Series, AnimeRating
from database.engine import AsyncSessionLocal
from database.queries import get_user_rating, add_or_update_rating

callback_router = Router()

PAGE_SIZE = 12


def player_keyboard(
    anime_id: int,
    episode: int,
    episodes: list,
    page: int = 0,
    is_last: bool = False,
    user_rated: bool = False
) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_episodes = episodes[start:end]
    total_pages = (len(episodes) - 1) // PAGE_SIZE if len(episodes) > 1 else 0

    buttons = []

    # Qismlar tugmalari — 4 ustun
    row = []
    for ep in page_episodes:
        is_current = ep.episode == episode
        text = f"[🎬 {ep.episode}]" if is_current else f"🎬 {ep.episode}"
        row.append(InlineKeyboardButton(
            text=text,
            callback_data=f"ep_{anime_id}_{ep.episode}"
        ))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Nav qatori
    nav = []
    if episode > episodes[0].episode:
        nav.append(InlineKeyboardButton(
            text="◀️ Oldingi",
            callback_data=f"ep_{anime_id}_{episode - 1}"
        ))

    nav.append(InlineKeyboardButton(
        text="🔗 Ulashish",
        url=f"https://t.me/share/url?url=https://t.me/kaworai_uz_bot?start%3Danime_{anime_id}"
    ))

    if episode < episodes[-1].episode:
        nav.append(InlineKeyboardButton(
            text="Keyingi ▶️",
            callback_data=f"ep_{anime_id}_{episode + 1}"
        ))
    elif page < total_pages:
        nav.append(InlineKeyboardButton(
            text="Keyingi ▶️",
            callback_data=f"eppage_{anime_id}_{page + 1}"
        ))

    if nav:
        buttons.append(nav)

    # Kaworai Pro
    buttons.append([InlineKeyboardButton(text="🟢 Kaworai Pro", callback_data="kawaii_pass")])

    # Menu va Muammo
    buttons.append([
        InlineKeyboardButton(text="🏠 Menu", callback_data="main_menu"),
        InlineKeyboardButton(text="⚠️ Muammo", callback_data="report_problem"),
    ])

    # Baho berish
    if is_last and not user_rated:
        buttons.append([InlineKeyboardButton(text="⭐ Baho berish", callback_data=f"rate_{anime_id}")])
    elif is_last and user_rated:
        buttons.append([InlineKeyboardButton(text="✅ Baho berilgan", callback_data=f"rated_{anime_id}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def edit_or_send_video(call: CallbackQuery, file_id: str, caption: str, kb: InlineKeyboardMarkup):
    try:
        media = InputMediaVideo(media=file_id, caption=caption, parse_mode="HTML")
        await call.message.edit_media(media=media, reply_markup=kb)
    except Exception:
        await call.message.answer_video(
            video=file_id,
            caption=caption,
            reply_markup=kb,
            parse_mode="HTML"
        )


# ====================== ANIME INFO ======================
@callback_router.callback_query(F.data.startswith("anime_info_"))
async def show_anime_info(call: CallbackQuery):
    anime_id = int(call.data.replace("anime_info_", ""))
    async with AsyncSessionLocal() as session:
        anime = await session.get(Anime, anime_id)
        if not anime:
            return await call.answer("❌ Anime topilmadi!", show_alert=True)
        ep_count_result = await session.execute(
            select(func.count(Series.id)).where(Series.anime_id == anime_id)
        )
        ep_count = ep_count_result.scalar() or 0

    genres_text = ", ".join(anime.genres) if anime.genres else "Nomalum"
    caption = (
        f"🎬 <b>{anime.title}</b>\n\n"
        f"📅 Yil: {anime.year}\n"
        f"🎭 Janr: {genres_text}\n"
        f"⭐ Reyting: {anime.rating} ({anime.rating_count} ovoz)\n"
        f"📺 Qismlar: {ep_count} ta\n\n"
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


# ====================== WATCH ======================
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

    kb = player_keyboard(
        anime_id=anime_id,
        episode=first_ep.episode,
        episodes=episodes,
        page=0,
        is_last=is_last,
        user_rated=user_rated
    )

    await call.message.answer_video(
        video=first_ep.file_id,
        caption=(
            f"🎬 <b>{anime.title}</b>\n"
            f"▶️ {first_ep.episode}-qism | 📺 Jami: {total} qism"
        ),
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


# ====================== EPISODE ======================
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

    ep_index = next(i for i, e in enumerate(episodes) if e.episode == episode)
    page = ep_index // PAGE_SIZE

    kb = player_keyboard(
        anime_id=anime_id,
        episode=episode,
        episodes=episodes,
        page=page,
        is_last=is_last,
        user_rated=user_rated
    )

    await edit_or_send_video(
        call,
        ep.file_id,
        f"🎬 <b>{anime.title}</b>\n▶️ {episode}-qism | 📺 Jami: {total} qism",
        kb
    )
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
        user_rating = await get_user_rating(session, anime_id, call.from_user.id)

    if not episodes:
        return await call.answer("❌ Qismlar yo'q!", show_alert=True)

    start = page * PAGE_SIZE
    first_on_page = episodes[start] if start < len(episodes) else episodes[0]
    is_last = first_on_page.episode == max(e.episode for e in episodes)
    user_rated = user_rating is not None

    kb = player_keyboard(
        anime_id=anime_id,
        episode=first_on_page.episode,
        episodes=episodes,
        page=page,
        is_last=is_last,
        user_rated=user_rated
    )

    await edit_or_send_video(
        call,
        first_on_page.file_id,
        f"🎬 <b>{anime.title}</b>\n▶️ {first_on_page.episode}-qism | 📺 Jami: {len(episodes)} qism",
        kb
    )
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
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="close_rating")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.answer(
        "⭐ <b>Anime uchun baho bering (1-10):</b>\n\n"
        "1 — Yomon | 5 — O'rtacha | 10 — A'lo",
        reply_markup=kb,
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


@callback_router.callback_query(F.data == "close_rating")
async def close_rating(call: CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()


@callback_router.callback_query(F.data.startswith("rated_"))
async def already_rated(call: CallbackQuery):
    await call.answer("✅ Siz allaqachon baho bergansiz!", show_alert=True)


# ====================== MAIN MENU ======================
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


@callback_router.callback_query(F.data == "report_problem")
async def report_problem(call: CallbackQuery):
    await call.answer("🚧 Tez kunda!", show_alert=True)


@callback_router.callback_query(F.data == "kawaii_pass")
async def kawaii_pass_cb(call: CallbackQuery):
    await call.answer("🟢 Kaworai Pro tez kunda ishga tushadi!", show_alert=True)


@callback_router.callback_query(F.data == "noop")
async def noop_cb(call: CallbackQuery):
    await call.answer()