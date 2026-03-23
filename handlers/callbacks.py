from aiogram import Router, F
from aiogram.types import CallbackQuery, InputMediaVideo
from utils.redis_helpers import set_watching
# from keyboards.inline import next_episode_kb

callback_router = Router()

@router.callback_query(F.data.startswith("watch_"))
async def watch(cb: CallbackQuery):
    anime_id = int(cb.data.split("_")[1])
    await set_watching(cb.from_user.id, anime_id)
    await cb.message.edit_media(
        media=InputMediaVideo(media="BQACAgI...", caption="📺 1-qism"),
        reply_markup=next_episode_kb(anime_id)
    )
    await cb.answer()