from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from states.admin_states import AddAnime, AddPartner
from database.models import Anime, Admin, User  # User ni ham import qilish kerak bo'lishi mumkin
from database.engine import AsyncSession
from sqlalchemy import select, func
from config import config

admin_router = Router()

# Vaqtincha oddiy reply keyboard (inline emas)
simple_admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Anime qo'shish")],
        [KeyboardButton(text="📊 Statistika")],
        [KeyboardButton(text="🔙 Chiqish")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

@router.message(F.text == "/admin")
async def admin_entry(msg: Message, state: FSMContext):
    async with AsyncSession() as s:
        admin = await s.get(Admin, msg.from_user.id)
        
        if not admin:
            if msg.from_user.id == config.ADMIN_ID:
                await s.add(Admin(telegram_id=config.ADMIN_ID, role="owner"))
                await s.commit()
                admin = await s.get(Admin, config.ADMIN_ID)
            else:
                await msg.answer("Siz admin emassiz.")
                return

    if admin.role == "owner":
        await msg.answer("🛠 Owner Admin Panel ochildi", reply_markup=simple_admin_kb)
    else:
        await msg.answer("🛠 Partner Admin Panel ochildi", reply_markup=simple_admin_kb)


@router.message(F.text == "➕ Anime qo'shish")
async def add_anime(msg: Message, state: FSMContext):
    await msg.answer("🆔 Anime ID kiriting:")
    await state.set_state(AddAnime.waiting_id)


@router.message(F.text == "📊 Statistika")
async def stats(msg: Message):
    async with AsyncSession() as s:
        total_u = await s.scalar(select(func.count(User.telegram_id)))
        total_a = await s.scalar(select(func.count(Anime.id)))
        # today_u va top uchun real query yozish mumkin, hozircha oddiy
        top = "Hozircha top anime yo'q (query qo'shish kerak)"

    await msg.answer(
        f"📊 Statistika:\n"
        f"Umumiy foydalanuvchilar: {total_u or 0}\n"
        f"Umumiy anime soni: {total_a or 0}\n"
        f"Top anime: {top}"
    )


# Agar boshqa handlerlar bo'lsa, ularni saqlab qo'ying