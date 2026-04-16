from aiogram.fsm.state import State, StatesGroup


# 🔹 Anime qo‘shish
class AddAnime(StatesGroup):
    waiting_id = State()
    waiting_title = State()
    waiting_type = State()
    waiting_desc = State()
    waiting_genres = State()
    waiting_tags = State()
    waiting_mood = State()
    waiting_year = State()
    waiting_rating = State()
    waiting_total_episodes = State()
    waiting_duration = State()
    waiting_status = State()
    waiting_popularity = State()
    waiting_related = State()
    waiting_pro_lock = State()
    waiting_hidden_gem = State()
    waiting_poster = State()
    waiting_inline_url = State()
    waiting_trailer = State()


# 🔹 Kanal qo‘shish
class AddChannel(StatesGroup):
    waiting_name = State()
    waiting_url = State()
    waiting_type = State()
    waiting_channel_id = State()


# 🔹 Anime tahrirlash
class EditAnime(StatesGroup):
    waiting_anime_id = State()
    waiting_field = State()
    waiting_value = State()
    picking_genres = State()
    waiting_episode_select = State()
    waiting_episode_video = State()
    waiting_delete_anime_id = State()
    waiting_delete_ep_anime_id = State()
    waiting_delete_ep_from = State()
    waiting_delete_ep_to = State()


# 🔹 Broadcast (xabar yuborish)
class BroadcastState(StatesGroup):
    waiting_content = State()
    waiting_media_type = State()
    waiting_caption = State()
    waiting_confirm = State()
    waiting_anime_id = State()
    waiting_anime_media_type = State()
    waiting_anime_post_caption = State()
    waiting_anime_post_confirm = State()
    waiting_genre_name = State()
    waiting_genre_channel = State()


# 🔹 PRO tizim
class AdminProState(StatesGroup):
    waiting_user_id = State()
    waiting_pro_days = State()
    waiting_msg_text = State()


# 🔹 Episode qo‘shish (MUHIM — alohida class!)
class AddEpisodeState(StatesGroup):
    waiting_anime_id = State()
    waiting_from_ep = State()
    waiting_to_ep = State()
