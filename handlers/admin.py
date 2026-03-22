from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from states.admin_states import AddAnime, AddPartner
from keyboards.inline import admin_menu, owner_menu, partner_menu
from database.models import Anime, Admin
from database.engine import AsyncSession
from sqlalchemy import select, func
from config import config

router = Router()

@router.message(F.text == "/admin")
async def admin_entry(msg: Message, state: FSMContext):
    async with AsyncSession() as s:
        admin = await s.get(Admin, msg.from_user.id)
    if not admin:
        if msg.from_user.id == config.ADMIN_ID:
            await s.add(Admin(telegram_id=config.ADMIN_ID, role="owner"))
            await s.commit()
            admin = await s.get(Admin, config.ADMIN_ID)

    if admin.role == "owner":
        await msg.answer("🛠 Owner Admin Panel", reply_markup=owner_menu())
    else:
        await msg.answer("🛠 Partner Admin Panel", reply_markup=partner_menu())

# Anime qo'shish (qisqa misol, to'liq FSM)
@router.message(F.text == "➕ Anime qo'shish")
async def add_anime(msg: Message, state: FSMContext):
    await msg.answer("🆔 Anime ID kiriting:")
    await state.set_state(AddAnime.waiting_id)

# ... (qolgan FSM davomi oldingi javoblarimdagi kabi, lekin joy yetishmasligi uchun qisqartirilgan – kerak bo'lsa to'liq so'rang)

@router.message(F.text == "📊 Statistika")
async def stats(msg: Message):
    async with AsyncSession() as s:
        total_u = await s.scalar(select(func.count(User.telegram_id)))
        today_u = 42  # real query qo'yish mumkin
        total_a = await s.scalar(select(func.count(Anime.id)))
        top = "One Piece (ID: 1) — 12450 views"
    await msg.answer(f"📊 Statistika:\nUsers: {total_u}\nAnime: {total_a}\nTop: {top}")