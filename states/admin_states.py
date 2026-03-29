from aiogram.fsm.state import State, StatesGroup


class AddAnime(StatesGroup):
    waiting_id = State()
    waiting_title = State()
    waiting_desc = State()
    waiting_genres = State()
    waiting_year = State()
    waiting_rating = State()
    waiting_total_episodes = State()
    waiting_poster = State()
    waiting_inline_url = State()
    waiting_trailer = State()


class AddChannel(StatesGroup):
    waiting_name = State()
    waiting_url = State()
    waiting_type = State()
    waiting_channel_id = State()


class EditAnime(StatesGroup):
    # Tahrirlash
    waiting_anime_id = State()
    waiting_field = State()
    waiting_value = State()
    waiting_episode_select = State()
    waiting_episode_video = State()
    # Anime o'chirish
    waiting_delete_anime_id = State()
    # Qism oraliq o'chirish
    waiting_delete_ep_anime_id = State()
    waiting_delete_ep_from = State()
    waiting_delete_ep_to = State()


class BroadcastState(StatesGroup):
    waiting_content = State()
    waiting_media_type = State()
    waiting_caption = State()
    waiting_confirm = State()
    waiting_anime_id = State()
    waiting_anime_post_caption = State()
    waiting_anime_post_confirm = State()