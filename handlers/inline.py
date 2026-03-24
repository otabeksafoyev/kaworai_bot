from aiogram import Router, types

inline_router = Router()

@inline_router.inline_query()
async def empty_inline_handler(query: types.InlineQuery):
    # Hozircha bo'sh natija, lekin xato bermasligi uchun kerak
    await query.answer([], switch_pm_text="Anime qidirish...", switch_pm_parameter="search")