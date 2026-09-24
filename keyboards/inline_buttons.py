# keyboards/inline_buttons.py
# Kawaii Pass menyusi uchun tugmalar

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_kawaii_pass_kb():
    """Pro obuna narxlari (pro_payment.py dagi PLANS bilan bir xil)."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❤️ 1 oylik - 9.000 so'm", callback_data="pro_plan_1"))
    builder.row(InlineKeyboardButton(text="🔥 2 oylik - 16.000 so'm", callback_data="pro_plan_2"))
    builder.row(InlineKeyboardButton(text="❤️‍🔥 3 oylik - 21.000 so'm", callback_data="pro_plan_3"))
    builder.row(InlineKeyboardButton(text="⚡ 6 oylik - 39.000 so'm", callback_data="pro_plan_6"))
    builder.row(InlineKeyboardButton(text="🌙 1 yillik - 69.000 so'm", callback_data="pro_plan_12"))
    builder.row(InlineKeyboardButton(text="🔙 Ortga", callback_data="main_menu"))
    return builder.as_markup()
