import asyncio
from types import SimpleNamespace as NS

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import handlers.admin_ai as m
from states.admin_states import AddAnimeAI


class FakeMsg:
    def __init__(self, text=None):
        self.text = text
        self.from_user = NS(id=1, is_bot=False)
        self.sent = []
        self.bot = None

    async def answer(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return NS(delete=self._noop)

    async def _noop(self):
        return None


class FakeCall:
    def __init__(self, data):
        self.data = data
        self.from_user = NS(id=1)
        self.message = FakeMsg()

    async def answer(self, *a, **k):
        return None


async def _admin(_):
    return True


def test_type_step_and_build_receives_chosen_type(monkeypatch):
    seen = {}

    async def fake_build(english, content_type="anime"):
        seen["args"] = (english, content_type)
        return {"content_type": content_type, "desc": "Tavsif", "genres": ["Drama"], "tags": ["x"], "mood": ["dark"],
                "year": 2021, "rating": 7.8, "total_episodes": 9, "episodes_count": 9, "duration": 60,
                "status": "completed", "sources": ["TMDB"], "matched_title": "Squid Game", "note": "",
                "errors": ["Gemini: bepul limit tugagan (429)"]}

    monkeypatch.setattr(m, "is_admin", _admin)
    monkeypatch.setattr(m, "build_content_info", fake_build)

    async def run():
        state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))
        await state.set_state(AddAnimeAI.waiting_title)
        await state.update_data(anime_id=5)

        # 1) nom -> tur tanlash klaviaturasi (4 ta tur)
        msg = FakeMsg("Kalmar o'yini")
        await m.ai_get_title(msg, state)
        assert await state.get_state() == AddAnimeAI.waiting_type.state
        kb = msg.sent[-1][1]
        assert [b.callback_data for r in kb.inline_keyboard for b in r] == [f"aitype:{k}" for k in m.TYPE_LABEL]

        # 2) tur tanlandi
        call = FakeCall("aitype:dorama")
        await m.ai_pick_type(call, state)
        assert await state.get_state() == AddAnimeAI.waiting_english.state
        assert (await state.get_data())["chosen_type"] == "dorama"

        # 3) inglizcha nom -> build tanlangan tur bilan chaqiriladi, natijada tur o'zgarmaydi
        msg2 = FakeMsg("Squid Game")
        await m.ai_get_english(msg2, state)
        assert seen["args"] == ("Squid Game", "dorama")
        assert await state.get_state() == AddAnimeAI.confirm.state
        data = await state.get_data()
        assert data["content_type"] == "dorama" and data["episodes_count"] == 9
        preview = msg2.sent[-1][0]
        assert "Dorama" in preview and "bepul limit tugagan" in preview

    asyncio.run(run())


def test_unknown_type_callback_is_rejected(monkeypatch):
    monkeypatch.setattr(m, "is_admin", _admin)

    async def run():
        state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))
        await state.set_state(AddAnimeAI.waiting_type)
        await m.ai_pick_type(FakeCall("aitype:hack"), state)
        assert await state.get_state() == AddAnimeAI.waiting_type.state

    asyncio.run(run())
