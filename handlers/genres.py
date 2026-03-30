import json
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from database.models import Anime
from database.engine import AsyncSessionLocal

genre_router = Router()

GENRES = {
    "Jang": "⚔️ Jang",
    "Sarguzasht": "🗺️ Sarguzasht",
    "Komediya": "😂 Komediya",
    "Drama": "🎭 Drama",
    "Fantaziya": "🧙 Fantaziya",
    "Qo'rqinchli": "👻 Qo'rqinchli",
    "Sirli": "🔍 Sirli",
    "Romantika": "❤️ Romantika",
    "Ilmiy fantastika": "🚀 Ilmiy fantastika",
    "Oddiy hayot": "☕ Oddiy hayot",
    "Sport": "⚽ Sport",
    "G'ayritabiiy": "✨ G'ayritabiiy",
    "Triller": "😱 Triller",
    "Mexanik": "🤖 Mexanik",
    "Sehr": "🪄 Sehr",
    "Maktab": "🏫 Maktab",
    "Shonen": "👦 Shonen",
    "Shojo": "👧 Shojo",
    "Isekai": "🌀 Isekai",
    "Psixologik": "🧠 Psixologik",
}

# Bazadagi turli yozilish variantlarini normalize qilish
GENRE_ALIASES = {
    "Sci-Fi": "SciFi",
    "Slice of Life": "SliceOfLife",
    "sci-fi": "SciFi",
    "slice of life": "SliceOfLife",
    "action": "Action",
    "adventure": "Adventure",
    "comedy": "Comedy",
    "drama": "Drama",
    "fantasy": "Fantasy",
    "horror": "Horror",
    "mystery": "Mystery",
    "romance": "Romance",
    "scifi": "SciFi",
    "sliceoflife": "SliceOfLife",
    "sports": "Sports",
    "sport": "Sports",
    "supernatural": "Supernatural",
    "thriller": "Thriller",
    "mecha": "Mecha",
    "magic": "Magic",
    "school": "School",
    "shounen": "Shounen",
    "shoujo": "Shoujo",
    "isekai": "Isekai",
    "psychological": "Psychological",
}

GENRE_PAGE_SIZE = 8
ANIME_PAGE_SIZE = 6


def normalize_genre(g: str) -> str:
    """Genre stringini standart key ga aylantiradi."""
    g = g.strip()
    # To'g'ridan-to'g'ri alias tekshirish
    if g in GENRE_ALIASES:
        return GENRE_ALIASES[g]
    # Kichik harf bilan tekshirish
    if g.lower() in GENRE_ALIASES:
        return GENRE_ALIASES[g.lower()]
    # GENRES kalitlarida bormi tekshirish (case-insensitive)
    for key in GENRES:
        if key.lower() == g.lower():
            return key
    return g


def parse_genres(raw_genres) -> list:
    """
    Bazadan kelgan genres ni list ga aylantiradi.
    JSON list, JSON string, vergul bilan ajratilgan string — barchasini qabul qiladi.
    """
    if raw_genres is None:
        return []

    # Allaqachon list bo'lsa
    if isinstance(raw_genres, list):
        return raw_genres

    # String bo'lsa
    if isinstance(raw_genres, str):
        raw_genres = raw_genres.strip()
        # JSON parse
        try:
            parsed = json.loads(raw_genres)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        # Vergul bilan ajratilgan
        return [g.strip() for g in raw_genres.split(",") if g.strip()]

    return []


def genres_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    genre_keys = list(GENRES.keys())
    total_pages = (len(genre_keys) - 1) // GENRE_PAGE_SIZE
    start = page * GENRE_PAGE_SIZE
    end = start + GENRE_PAGE_SIZE
    page_genres = genre_keys[start:end]

    buttons = []
    row = []
    for key in page_genres:
        row.append(InlineKeyboardButton(
            text=GENRES[key],
            callback_data=f"gshow:{key}:{page}"
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"gpage:{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"gpage:{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def anime_list_keyboard(animes: list, genre_key: str, from_page: int, page: int = 0) -> InlineKeyboardMarkup:
    total_pages = (len(animes) - 1) // ANIME_PAGE_SIZE if animes else 0
    start = page * ANIME_PAGE_SIZE
    end = start + ANIME_PAGE_SIZE
    page_animes = animes[start:end]

    buttons = []
    for anime in page_animes:
        buttons.append([InlineKeyboardButton(
            text=f"🎬 {anime.title}",
            callback_data=f"anime_info_{anime.id}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️ Oldingi",
            callback_data=f"glist:{genre_key}:{from_page}:{page - 1}"
        ))
    if page < total_pages:
        nav.append(InlineKeyboardButton(
            text="Keyingi ➡️",
            callback_data=f"glist:{genre_key}:{from_page}:{page + 1}"
        ))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(
        text="🔙 Janrlarga qaytish",
        callback_data=f"gpage:{from_page}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_animes_by_genre(genre_key: str) -> list:
    """DB dagi barcha animalardan genre_key ga moslarini qaytaradi."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Anime))
        all_animes = result.scalars().all()

        matched = []
        for anime in all_animes:
            genres_list = parse_genres(anime.genres)
            for g in genres_list:
                normalized = normalize_genre(g)
                if normalized == genre_key:
                    matched.append(anime)
                    break

        return matched


# ====================== JANRLAR RO'YXATI ======================

@genre_router.callback_query(F.data == "genres")
async def show_genres(call: CallbackQuery):
    kb = genres_keyboard(page=0)
    try:
        await call.message.edit_caption(
            caption="🎭 <b>Janr tanlang:</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception:
        await call.message.answer(
            "🎭 <b>Janr tanlang:</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )
    await call.answer()


# ====================== JANR SAHIFASI ======================

@genre_router.callback_query(F.data.startswith("gpage:"))
async def genre_page(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    kb = genres_keyboard(page=page)
    try:
        await call.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        await call.message.answer(
            "🎭 <b>Janr tanlang:</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )
    await call.answer()


# ====================== JANR BO'YICHA ANIMLAR ======================

@genre_router.callback_query(F.data.startswith("gshow:"))
async def show_genre_animes(call: CallbackQuery):
    parts = call.data.split(":")
    genre_key = parts[1]
    from_page = int(parts[2])

    matched = await get_animes_by_genre(genre_key)
    genre_uz = GENRES.get(genre_key, genre_key)

    if not matched:
        await call.answer(f"😔 {genre_uz} janrida anime topilmadi!", show_alert=True)
        return

    kb = anime_list_keyboard(matched, genre_key, from_page, page=0)
    text = f"🎭 <b>{genre_uz}</b> janridagi animalar ({len(matched)} ta):"

    try:
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# ====================== ANIME RO'YXATI SAHIFASI ======================

@genre_router.callback_query(F.data.startswith("glist:"))
async def genre_anime_page(call: CallbackQuery):
    parts = call.data.split(":")
    genre_key = parts[1]
    from_page = int(parts[2])
    page = int(parts[3])

    matched = await get_animes_by_genre(genre_key)
    genre_uz = GENRES.get(genre_key, genre_key)

    kb = anime_list_keyboard(matched, genre_key, from_page, page=page)
    text = f"🎭 <b>{genre_uz}</b> janridagi animalar ({len(matched)} ta):"

    try:
        await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()