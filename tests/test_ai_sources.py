import asyncio

import utils.ai_anime as ai


def _run(coro):
    return asyncio.run(coro)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_gemini_state():
    """Modul darajasidagi 'ishlagan model' keshi testlarga ta'sir qilmasin."""
    ai._gemini_state.update(model=None, listed=[], listed_at=0.0)
    yield


ANIME_ITEM = {
    "title": "Ore dake Level Up na Ken", "title_english": "Solo Leveling", "type": "TV", "episodes": 12,
    "status": "Finished Airing", "duration": "24 min per ep", "year": 2024, "score": 8.2,
    "genres": [{"name": "Action"}, {"name": "Fantasy"}], "synopsis": "Hunters fight gates.",
    "images": {"jpg": {"large_image_url": "https://x/y.jpg"}},
}
GEMINI_OK = {"description_uz": "Ovchilar darvozalar bilan kurashadi.", "genres": ["Jang"], "tags": ["revenge", "battle", "bogus"],
             "mood": ["action", "intense"], "year": 2024, "episodes": 12, "duration": 24, "status": "completed"}


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
        self.status, self._p = status, (payload if payload is not None else {})

    async def json(self):
        return self._p

    async def text(self):
        return self._p if isinstance(self._p, str) else ""

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


# ─── Botning lug'ati, model topish va tarjima ────────────────────────

def test_ai_moods_and_tags_use_bots_own_vocabulary(monkeypatch):
    _patch(monkeypatch, jikan=([ANIME_ITEM], None), gemini=GEMINI_OK)
    info = _run(ai.build_content_info("Solo Leveling", "anime"))
    assert info["mood"] == ["action"]                    # "intense" botda yo'q — tashlab yuborildi
    assert "revenge" in info["tags"] and "battle" in info["tags"] and "bogus" not in info["tags"]
    assert all(m in ai.ALLOWED_MOODS for m in info["mood"]) and all(t in ai.ALLOWED_TAGS for t in info["tags"])


def test_mood_and_tags_derived_when_gemini_fails(monkeypatch):
    item = {**ANIME_ITEM, "genres": [{"name": "Action"}, {"name": "Adventure"}, {"name": "Fantasy"}],
            "themes": [{"name": "Isekai"}]}
    _patch(monkeypatch, jikan=([item], None), gemini=None)
    info = _run(ai.build_content_info("Solo Leveling", "anime"))
    assert {"action", "fantasy"} <= set(info["mood"]) and len(info["mood"]) <= 3
    assert "adventure" in info["tags"] and "isekai" in info["tags"]


def test_description_is_translated_not_left_english(monkeypatch):
    _patch(monkeypatch, jikan=([ANIME_ITEM], None), gemini=None)

    async def fake_tr(session, text, errors):
        assert "(Source" not in text
        return "Ovchilar darvozalar bilan kurashadi."

    monkeypatch.setattr(ai, "_translate_uz", fake_tr)
    item = {**ANIME_ITEM, "synopsis": "Hunters fight gates. (Source: Crunchyroll)"}
    _patch(monkeypatch, jikan=([item], None), gemini=None)
    info = _run(ai.build_content_info("Solo Leveling", "anime"))
    assert info["desc"] == "Ovchilar darvozalar bilan kurashadi." and "Google Tarjima" in info["sources"]


def test_description_empty_when_everything_fails_not_english(monkeypatch):
    async def fail_tr(session, text, errors):
        errors.append("Tarjima: status 429")
        return None

    monkeypatch.setattr(ai, "_translate_uz", fail_tr)
    _patch(monkeypatch, jikan=([ANIME_ITEM], None), gemini=None)
    info = _run(ai.build_content_info("Solo Leveling", "anime"))
    assert info["desc"] == "" and any("Tarjima" in e for e in info["errors"])


def test_clean_synopsis_and_mood_aliases():
    assert ai.clean_synopsis("Story. (Source: Crunchyroll) [Written by MAL Rewrite]") == "Story."
    assert ai.normalize_mood("Jangari") == "action" and ai.normalize_mood("kulgili") == "funny"
    assert ai.normalize_mood("emotional") is None
    assert ai.derive_mood_tags(["horror", "mystery"])[0][:2] == ["scary", "mystery"] or "scary" in ai.derive_mood_tags(["horror"])[0]


def test_gemini_follows_404_hint_to_new_model(monkeypatch):
    monkeypatch.setattr(ai.config, "GEMINI_API_KEY", "k", raising=False)
    monkeypatch.setattr(ai.config, "GEMINI_MODEL", "old", raising=False)
    monkeypatch.setattr(ai.config, "GEMINI_FALLBACK_MODELS", "", raising=False)
    s = _Session({"old": (404, "This model is no longer available. Please update your code to use models/new-flash for the latest"),
                  "new-flash": (200, _gemini_payload({"description_uz": "ok"}))})
    out = _run(ai._gemini_enrich(s, "X", None, "anime", []))
    assert out == {"description_uz": "ok"} and s.used == ["old", "new-flash"]
    assert ai._gemini_state["model"] == "new-flash"          # keyingi safar darrov shu ishlatiladi


def test_rank_models_prefers_newest_stable_flash():
    names = ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash-image",
             "gemini-3.9-flash-preview", "gemini-3.8-pro", "embedding-001", "gemini-3.8-flash-live"]
    assert ai._rank_models(names) == ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.9-flash-preview"]


class _JsonResp:
    def __init__(self, data, status=200):
        self._d, self.status = data, status

    async def json(self, content_type=None):
        return self._d

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def test_translate_uz_joins_chunks_and_parses_google_format():
    class S:
        def __init__(self):
            self.sent = []

        def post(self, url, params=None, data=None):
            self.sent.append((params["tl"], data["q"]))
            return _JsonResp([[["Ovchi kuchayadi. ", "The hunter levels up. ", None, None], ["Dunyo", "World", None, None]], None, "en"])

    s, errors = S(), []
    text = "The hunter levels up. " * 3
    out = _run(ai._translate_uz(s, text, errors))
    assert out == "Ovchi kuchayadi. Dunyo" and s.sent[0][0] == "uz" and not errors

    class Bad:
        def post(self, url, params=None, data=None):
            return _JsonResp(None, status=429)

    errors = []
    assert _run(ai._translate_uz(Bad(), "Hello.", errors)) is None and "429" in errors[0]


def test_discover_models_lists_only_usable_flash_models(monkeypatch):
    models = [{"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
              {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
              {"name": "models/gemini-3.8-pro", "supportedGenerationMethods": ["generateContent"]},
              {"name": "models/text-embedding-9", "supportedGenerationMethods": ["embedContent"]},
              {"name": "models/gemini-3.8-flash-image", "supportedGenerationMethods": ["generateContent"]}]

    class S:
        def get(self, url, params=None, headers=None):
            return _JsonResp({"models": models})

    out = _run(ai._discover_models(S(), "k"))
    assert out == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert ai._gemini_state["listed"] == out        # keshlandi
