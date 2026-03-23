from aiogram import Router, F, types
from aiogram.types import CallbackQuery
from keyboards.inline import main_menu, genres_keyboard, anime_actions, next_episode_kb
# Agar database ishlatayotgan bo'lsangiz:
# from database.engine import AsyncSession

# 1. Routerni to'g'ri nom bilan e'lon qilamiz
callback_router = Router()

# 2. Barcha handlerlarda @router emas, @callback_router ishlatamiz

@callback_router.callback_query(F.data.startswith("watch_"))
async def watch_anime(call: CallbackQuery):
    anime_id = call.data.split("_")[1]
    # Anime ko'rish logikasi bu yerda bo'ladi
    await call.message.answer(f"Anime ID: {anime_id} yuklanmoqda...")
    await call.answer()

@callback_router.callback_query(F.data == "main_menu")
async def back_to_main(call: CallbackQuery):
    await call.message.edit_text("Asosiy menyu", reply_markup=main_menu())
    await call.answer()

@callback_router.callback_query(F.data == "show_genres")
async def show_genres_callback(call: CallbackQuery):
    await call.message.edit_text("Janrni tanlang:", reply_markup=genres_keyboard())
    await call.answer()

# Agar xatolik bergan boshqa qatorlar bo'lsa, ularni ham @callback_router ga o'tkazing