from aiogram.fsm.state import State, StatesGroup

class AddAnime(StatesGroup):
    waiting_id       = State()
    waiting_title    = State()
    waiting_desc     = State()
    waiting_poster   = State()       # photo yuboriladi → file_id saqlanadi
    waiting_genres   = State()
    waiting_year     = State()
    waiting_series   = State()       # har bir seriya uchun alohida episode + file_id

class AddPartner(StatesGroup):
    waiting_id       = State()
    waiting_nickname = State()

class PublishAnime(StatesGroup):
    waiting_confirm  = State()