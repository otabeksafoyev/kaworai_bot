from aiogram.fsm.state import State, StatesGroup


class AddAnime(StatesGroup):
    waiting_id = State()
    waiting_title = State()
    waiting_desc = State()
    waiting_genres = State()
    waiting_year = State()
    waiting_rating = State()
    waiting_poster = State()
    waiting_inline_url = State()
    waiting_trailer = State()


class EditAnime(StatesGroup):
    waiting_anime_id = State()
    waiting_field = State()
    waiting_value = State()


class AddChannel(StatesGroup):
    waiting_name = State()
    waiting_url = State()
    waiting_type = State()
    waiting_channel_id = State()


class BroadcastState(StatesGroup):
    waiting_type = State()
    waiting_anime_id = State()
    waiting_media_type = State()
    waiting_content = State()