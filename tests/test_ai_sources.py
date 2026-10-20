import asyncio

import utils.ai_anime as ai


def _run(coro):
    return asyncio.run(coro)


ANIME_ITEM = {
    "title": "Ore dake Level Up na Ken", "title_english": "Solo Leveling", "type": "TV", "episodes": 12,
    "status": "Finished Airing", "duration": "24 min per ep", "year": 2024, "score": 8.2,
    "genres": [{"name": "Action"}, {"name": "Fantasy"}], "synopsis": "Hunters fight gates.",
    "images": {"jpg": {"large_image_url": "https://x/y.jpg"}},
}
GEMINI_OK = {"description_uz": "Ovchilar darvozalar bilan kurashadi.", "genres": ["Jang"], "tags": ["hunter", "levelup"],
             "mood": ["intense"], "year": 2024, "episodes": 12, "duration": 24, "status": "completed"}


def _patch(monkeypatch, jikan=None, anilist=None, gemini=None, tmdb=None):
    calls = {"jikan": 0, "anilist": 0, "tmdb": 0}

    async def j(session, q):
        calls["jikan"] += 1
        return jikan if jikan is not None else ([], "so'rov limiti (429)")

    async def a(session, q):
        calls["anilist"] += 1
        return anilist if anilist is not None else ([], "status 500")

    async def g(session, title, facts, ctype, errors):
        if gemini is None:
            errors.append("Gemini: GEMINI_API_KEY qo'yilmagan")
        return gemini

    async def t(session, q, ctype, errors):
        calls["tmdb"] += 1
        return tmdb

    monkeypatch.setattr(ai, "_jikan_search", j)
    monkeypatch.setattr(ai, "_anilist_search", a)
    monkeypatch.setattr(ai, "_gemini_enrich", g)
    monkeypatch.setattr(ai, "_tmdb_facts", t)
    return calls


def test_anime_falls_back_to_anilist_when_jikan_fails(monkeypatch):
    calls = _patch(monkeypatch, anilist=([ANIME_ITEM], None), gemini=GEMINI_OK)
    info = _run(ai.build_content_info("Solo Leveling", "anime"))
    assert info["sources"] == ["AniList", "Gemini AI"]
    assert any("MyAnimeList" in e for e in info["errors"])  # Jikan xatosi ko'rinadi
    assert info["year"] == 2024 and info["episodes_count"] == 12 and info["status"] == "completed"
    assert info["content_type"] == "anime" and calls["tmdb"] == 0


def test_everything_fails_reports_reasons(monkeypatch):
    _patch(monkeypatch)  # Jikan 429, AniList 500, Gemini kalit yo'q
    info = _run(ai.build_content_info("Solo Leveling", "anime"))
    assert info["sources"] == []
    text = " | ".join(info["errors"])
    assert "MyAnimeList" in text and "AniList" in text and "GEMINI_API_KEY" in text
    assert info["content_type"] == "anime"


def test_chosen_type_is_kept_and_movie_needs_exact_match(monkeypatch):
    # Jikan boshqa kontent qaytaradi — "kino" uchun qabul qilinmasligi kerak
    calls = _patch(monkeypatch, jikan=([ANIME_ITEM], None), anilist=([], None), gemini={**GEMINI_OK, "episodes": None})
    info = _run(ai.build_content_info("Parasite", "movie"))
    assert info["content_type"] == "movie" and info["matched_title"] == ""
    assert info["episodes_count"] == 1  # kino — 1 qism
    assert "MyAnimeList" not in info["sources"]
    assert calls["jikan"] >= 1


def test_serial_and_dorama_skip_anime_sources(monkeypatch):
    calls = _patch(monkeypatch, jikan=([ANIME_ITEM], None), gemini={**GEMINI_OK, "episodes": 16, "year": 2022})
    for t in ("serial", "dorama"):
        info = _run(ai.build_content_info("Extraordinary Attorney Woo", t))
        assert info["content_type"] == t and info["episodes_count"] == 16 and info["year"] == 2022
    assert calls["jikan"] == 0 and calls["anilist"] == 0 and calls["tmdb"] == 2


def test_tmdb_facts_win_over_gemini_numbers(monkeypatch):
    tmdb = {"matched_title": "Squid Game", "year": 2021, "rating": 7.8, "total_episodes": 9, "episodes_count": 9,
            "duration": 60, "status": "completed", "genres": ["Drama"], "synopsis_en": "x", "image_url": None}
    _patch(monkeypatch, gemini={**GEMINI_OK, "episodes": 99, "year": 1900}, tmdb=tmdb)
    info = _run(ai.build_content_info("Squid Game", "serial"))
    assert info["sources"] == ["TMDB", "Gemini AI"] and info["episodes_count"] == 9 and info["year"] == 2021
    assert info["rating"] == 7.8


def test_season_not_found_blanks_numbers(monkeypatch):
    _patch(monkeypatch, jikan=([ANIME_ITEM], None), gemini={**GEMINI_OK, "episodes": 99, "year": 1999})
    info = _run(ai.build_content_info("Solo Leveling season 3", "anime"))
    assert "3-fasl" in info["note"] and info["year"] is None and info["episodes_count"] == 0  # AI raqamlari ham ishlatilmaydi


# --- Gemini zaxira modellari (haqiqiy _gemini_enrich, soxta sessiya bilan)
class _Resp:
    def __init__(self, status, payload=None):
        self.status, self._p = status, payload or {}

    async def json(self):
        return self._p

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    def __init__(self, plan):
        self.plan, self.used = plan, []

    def post(self, url, **kw):
        model = url.split("/models/")[1].split(":")[0]
        self.used.append(model)
        return _Resp(*self.plan[model])


def _gemini_payload(d):
    import json
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(d)}]}}]}


def test_gemini_uses_fallback_model_on_quota(monkeypatch):
    monkeypatch.setattr(ai.config, "GEMINI_API_KEY", "k", raising=False)
    monkeypatch.setattr(ai.config, "GEMINI_MODEL", "m1", raising=False)
    monkeypatch.setattr(ai.config, "GEMINI_FALLBACK_MODELS", "m2,m3", raising=False)
    s = _Session({"m1": (429,), "m2": (200, _gemini_payload({"description_uz": "ok"}))})
    errors = []
    out = _run(ai._gemini_enrich(s, "X", None, "anime", errors))
    assert out == {"description_uz": "ok"} and s.used == ["m1", "m2"] and errors == []


def test_gemini_bad_key_stops_and_reports(monkeypatch):
    monkeypatch.setattr(ai.config, "GEMINI_API_KEY", "bad", raising=False)
    monkeypatch.setattr(ai.config, "GEMINI_MODEL", "m1", raising=False)
    monkeypatch.setattr(ai.config, "GEMINI_FALLBACK_MODELS", "m2", raising=False)
    s = _Session({"m1": (400,), "m2": (200, _gemini_payload({}))})
    errors = []
    assert _run(ai._gemini_enrich(s, "X", None, "anime", errors)) is None
    assert s.used == ["m1"] and "kalit noto'g'ri" in errors[0]


def test_preview_shows_error_reasons_and_chosen_type():
    from handlers.admin_ai import _render_preview

    data = {
        "anime_id": 958, "title": "Yolg'izlikda Daraja Ko'tarish", "content_type": "dorama", "genres": [], "tags": [],
        "mood": [], "status": "ongoing", "inline_thumbnail_url": None,
        "ai": {"sources": [], "matched_title": "", "note": "",
               "errors": ["MyAnimeList: so'rov limiti (429)", "Gemini: gemini-flash-latest: bepul limit tugagan (429)"]},
    }
    text = _render_preview(data)
    assert "hech narsa topilmadi" in text and "limiti (429)" in text and "Dorama" in text
    assert "Aniq manbada topilmadi" in text
