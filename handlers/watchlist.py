"""
handlers/watchlist.py — "Keyinroq ko'rish" (Watchlist) handler

Foydalanuvchi anime kartochkasidagi "📋 Keyinroq ko'rish" tugmasini bosib
anime saqlaydi. Asosiy menyuda "📋 Ro'yxatim" tugmasi bilan ko'radi.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.engine import AsyncSessionLocal
from database.queries import (
    add_to_watchlist,
    get_watchlist,
    get_watchlist_count,
    is_in_watchlist,
    remove_from_watchlist,
)

logger = logging.getLogger(__name__)

watchlist_router = Router()

WATCHLIST_PAGE_SIZE = 5


@watchlist_router.callback_query(F.data.startswith("wl_add_"))
async def watchlist_add(call: CallbackQuery):
    """Animeni watchlistga qo'shish yoki olib tashlash (toggle)."""
    anime_id = int(call.data.replace("wl_add_", ""))
    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        if await is_in_watchlist(session, user_id, anime_id):
            # Allaqachon bor — o'chiramiz
            await remove_from_watchlist(session, user_id, anime_id)
            await call.answer("🗑 Ro'yxatdan olib tashlandi", show_alert=False)
        else:
            # Qo'shamiz — max 50 ta
            count = await get_watchlist_count(session, user_id)
            if count >= 50:
                await call.answer(
                    "❌ Ro'yxatda 50 ta limit. Birortasini o'chirib yangi qo'shing.",
                    show_alert=True,
                )
                return
            added = await add_to_watchlist(session, user_id, anime_id)
            if added:
                await call.answer("✅ Keyinroq ko'rish ro'yxatiga qo'shildi!", show_alert=False)
            else:
                await call.answer("ℹ️ Allaqachon ro'yxatda", show_alert=False)


@watchlist_router.callback_query(F.data == "my_watchlist")
async def show_watchlist(call: CallbackQuery):
    """Foydalanuvchining watchlist ro'yxatini ko'rsatish."""
    await _show_watchlist_page(call, page=0)


@watchlist_router.callback_query(F.data.startswith("wl_page_"))
async def watchlist_page(call: CallbackQuery):
    """Watchlist sahifalash."""
    page = int(call.data.replace("wl_page_", ""))
    await _show_watchlist_page(call, page=page)


@watchlist_router.callback_query(F.data.startswith("wl_remove_"))
async def watchlist_remove(call: CallbackQuery):
    """Watchlistdan o'chirish (ro'yxat sahifasidagi tugma orqali)."""
    anime_id = int(call.data.replace("wl_remove_", ""))
    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        removed = await remove_from_watchlist(session, user_id, anime_id)

    if removed:
        await call.answer("🗑 O'chirildi", show_alert=False)
        # Ro'yxatni yangilash
        await _show_watchlist_page(call, page=0)
    else:
        await call.answer("❌ Topilmadi", show_alert=True)


async def _show_watchlist_page(call: CallbackQuery, page: int = 0):
    """Watchlist sahifasini ko'rsatish."""
    user_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        all_items = await get_watchlist(session, user_id, limit=50)
        total = len(all_items)

    if not all_items:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")]
            ]
        )
        try:
            await call.message.edit_text(
                "📋 <b>Keyinroq ko'rish ro'yxati</b>\n\n"
                "😕 Ro'yxatingiz bo'sh.\n\n"
                "Anime kartochkasidagi <b>📋 Keyinroq ko'rish</b> tugmasini bosib qo'shing!",
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception:
            await call.message.answer(
                "📋 Ro'yxatingiz bo'sh.",
                reply_markup=kb,
                parse_mode="HTML",
            )
        await call.answer()
        return

    # Sahifalash
    total_pages = (total - 1) // WATCHLIST_PAGE_SIZE
    start = page * WATCHLIST_PAGE_SIZE
    page_items = all_items[start: start + WATCHLIST_PAGE_SIZE]

    text = f"📋 <b>Keyinroq ko'rish ro'yxati</b> ({total} ta)\n\n"
    kb = InlineKeyboardBuilder()

    for i, anime in enumerate(page_items, start=start + 1):
        lock = "🔒 " if anime.is_pro_locked else ""
        ep_info = f" ({anime.episodes_count} qism)" if anime.episodes_count else ""
        text += f"{i}. {lock}<b>{anime.title}</b>{ep_info}\n"

        kb.row(
            InlineKeyboardButton(
                text=f"▶️ {anime.title[:25]}",
                callback_data=f"anime_info_{anime.id}",
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"wl_remove_{anime.id}",
            ),
        )

    # Navigatsiya
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"wl_page_{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"wl_page_{page + 1}"))
    if nav:
        kb.row(*nav)

    kb.row(InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu"))

    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        try:
            await call.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
        except Exception:
            await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

    await call.answer()


def get_watchlist_toggle_button(anime_id: int, in_watchlist: bool) -> InlineKeyboardButton:
    """
    Anime kartochkasiga qo'shish uchun tugma qaytaradi.
    handlers/callbacks.py dagi anime_info da ishlatiladi.
    """
    if in_watchlist:
        return InlineKeyboardButton(
            text="🗑 Ro'yxatdan olib tashlash",
            callback_data=f"wl_add_{anime_id}",
        )
    return InlineKeyboardButton(
        text="📋 Keyinroq ko'rish",
        callback_data=f"wl_add_{anime_id}",
    )
