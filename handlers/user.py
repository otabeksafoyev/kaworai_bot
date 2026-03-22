from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaVideo, InputMediaPhoto
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from keyboards.inline import main_menu, genres_keyboard
from utils.redis_helpers import set_watching

router = Router()

@router.message(CommandStart())
async def cmd_start(msg: Message):
    photo_id = "AgACAgIAAxkBAAIB..."  # o'zingizning kawaii rasm file_id
    await msg.answer_photo(
        photo=photo_id,
        caption="🎌 <b>Kaworai Anime Bot</b>\nTanlang 👇",
        reply_markup=main_menu()
    )