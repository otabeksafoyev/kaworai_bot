"""
utils/ai_anime.py — kontent ma'lumotlarini avtomatik to'plash (bepul).

Tur (anime / kino / serial / dorama) ADMIN tomonidan tanlanadi, manba turga qarab:
  anime  → Jikan (MyAnimeList) → zaxira: AniList → Gemini (tavsif/teg/mood)
  kino   → Jikan/AniList (faqat nomi aniq mos kelsa) → TMDB (kalit bo'lsa) → Gemini
  serial, dorama → TMDB (TMDB_API_KEY bo'lsa) → Gemini

Hech bir manba javob bermasa — sababi `errors` ro'yxatida (admin ko'rib chiqishda ko'radi).
Natija dict'ining kalitlari `_save_anime` kutgan FSM kalitlariga mos.
"""

from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import re

import aiohttp

from data import config
from handlers.genres import GENRES, normalize_genre
from utils.recommendation import MOOD_MAP, TEXT_TO_MOOD

logger = logging.getLogger(__name__)

JIKAN_SEARCH_URL = "https://api.jikan.moe/v4/anime"
ANILIST_URL = "https://graphql.anilist.co"
TMDB_BASE = "https://api.themoviedb.org/3"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=25)
HTTP_HEADERS = {"User-Agent": "KaworaiBot/1.0 (+https://t.me/kaworai_uz_bot)"}

# Botning o'z filtrlari (utils/recommendation.py) bilan bir xil lug'at — shunda qo'shilgan kontent
# kayfiyat/teg/janr bo'yicha qidiruv va tavsiyalarda topiladi.
ALLOWED_MOODS = list(MOOD_MAP)
ALLOWED_TAGS = sorted({t for cfg in MOOD_MAP.values() for t in cfg["tags"]})
MOOD_UZ = {
    "sad": "G'amgin", "romantic": "Romantik", "dark": "Dark", "motivational": "Motivatsion",
    "action": "Jangari", "funny": "Kulgili", "mystery": "Sirli", "chill": "Chill",
    "fantasy": "Fantastik", "scary": "Qo'rqinchli",
}
_MOOD_ALIASES = {
    **{m: m for m in MOOD_MAP},
    **{kw.lower(): m for m, kws in TEXT_TO_MOOD.items() for kw in kws},
    **{label.lower(): m for m, label in MOOD_UZ.items()},
}


def normalize_mood(text: str | None) -> str | None:
    """'Jangari' / 'action' / 'kulgili' → botdagi mood kaliti."""
    return _MOOD_ALIASES.get((text or "").strip().lower())


def mood_label(key: str) -> str:
    return MOOD_UZ.get(key, key)
CONTENT_TYPES = ["anime", "movie", "serial", "dorama"]
STATUSES = ["ongoing", "completed", "announced"]

# Manba janr nomlari normalize_genre da bo'lmaganlari
_EXTRA_GENRE_MAP = {
    "suspense": "Triller",
    "crime": "Triller",
    "supernatural": "G'ayritabiiy",
    "super power": "G'ayritabiiy",
    "gore": "Qo'rqinchli",
}


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _to_int(v) -> int | None:
    try:
        n = int(float(v))
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


# ─── Jikan (MyAnimeList) ──────────────────────────────────────────────

async def _jikan_search(session: aiohttp.ClientSession, query: str) -> tuple[list[dict], str | None]:
    """(natijalar, xato_matni). Vaqtincha xatolarda 3 martagacha qayta urinadi."""
    params = {"q": query, "limit": 5, "sfw": "true"}
    err = None
    for attempt in range(3):
        try:
            async with session.get(JIKAN_SEARCH_URL, params=params) as resp:
                if resp.status == 200:
                    return (await resp.json()).get("data") or [], None
                err = "so'rov limiti (429)" if resp.status == 429 else f"status {resp.status}"
                if resp.status in (429, 500, 502, 503, 504) and attempt < 2:
                    await asyncio.sleep(1.2 * (attempt + 1))
                    continue
                return [], err
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            err = f"ulanib bo'lmadi ({type(e).__name__})"
            if attempt < 2:
                await asyncio.sleep(1.0)
    return [], err


# ─── AniList (zaxira manba; Jikan ishlamasa) ──────────────────────────

_ANILIST_QUERY = """
query ($search: String) {
  Page(perPage: 5) {
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      format status episodes duration seasonYear averageScore genres
      description(asHtml: false) coverImage { large }
      title { romaji english } synonyms
    }
  }
}"""
_ANILIST_STATUS = {
    "FINISHED": "Finished Airing", "RELEASING": "Currently Airing",
    "NOT_YET_RELEASED": "Not yet aired", "CANCELLED": "Finished Airing", "HIATUS": "Currently Airing",
}


def _anilist_as_jikan(item: dict) -> dict:
    """AniList yozuvini Jikan shakliga keltiradi — shunda butun qolgan mantiq bir xil ishlaydi."""
    t = item.get("title") or {}
    desc = re.sub(r"<[^>]+>", " ", item.get("description") or "")
    score = item.get("averageScore")
    duration = item.get("duration")
    return {
        "title": t.get("romaji") or t.get("english") or "",
        "title_english": t.get("english"),
        "titles": [{"title": s} for s in (item.get("synonyms") or [])],
        "type": "Movie" if item.get("format") == "MOVIE" else "TV",
        "episodes": item.get("episodes") or 0,
        "status": _ANILIST_STATUS.get(item.get("status") or "", "Finished Airing"),
        "duration": f"{duration} min per ep" if duration else None,
        "year": item.get("seasonYear"),
        "score": (score / 10) if score else 0,
        "genres": [{"name": g} for g in item.get("genres") or []],
        "synopsis": re.sub(r"\s+", " ", desc).strip(),
        "images": {"jpg": {"large_image_url": (item.get("coverImage") or {}).get("large")}},
    }


async def _anilist_search(session: aiohttp.ClientSession, query: str) -> tuple[list[dict], str | None]:
    try:
        async with session.post(ANILIST_URL, json={"query": _ANILIST_QUERY, "variables": {"search": query}}) as resp:
            if resp.status != 200:
                return [], "so'rov limiti (429)" if resp.status == 429 else f"status {resp.status}"
            media = (((await resp.json()).get("data") or {}).get("Page") or {}).get("media") or []
            return [_anilist_as_jikan(m) for m in media], None
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        return [], f"ulanib bo'lmadi ({type(e).__name__})"


# ─── TMDB (kino / serial / dorama; TMDB_API_KEY bo'lsa) ───────────────

_TMDB_STATUS = {
    "Ended": "completed", "Canceled": "completed", "Released": "completed",
    "Returning Series": "ongoing", "In Production": "announced", "Planned": "announced",
    "Post Production": "announced", "Rumored": "announced",
}


def _split_genre_names(names: list[str]) -> list[str]:
    out: list[str] = []
    for n in names:
        for piece in re.split(r"\s*&\s*|,", n):
            mapped = _EXTRA_GENRE_MAP.get(piece.strip().lower()) or normalize_genre(piece.strip())
            if mapped in GENRES and mapped not in out:
                out.append(mapped)
    return out


async def _tmdb_facts(session: aiohttp.ClientSession, query: str, content_type: str, errors: list[str]) -> dict | None:
    key = getattr(config, "TMDB_API_KEY", "") or ""
    if not key:
        return None
    kind = "movie" if content_type == "movie" else "tv"
    headers, params = {}, {"language": "en-US"}
    if key.startswith("eyJ"):  # v4 token
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    try:
        async with session.get(f"{TMDB_BASE}/search/{kind}", params={**params, "query": query}, headers=headers) as r:
            if r.status != 200:
                errors.append("TMDB: kalit noto'g'ri (401)" if r.status == 401 else f"TMDB: status {r.status}")
                return None
            results = (await r.json()).get("results") or []
        if not results:
            return None
        best = next((x for x in results if _norm(x.get("title") or x.get("name")) == _norm(query)), results[0])
        async with session.get(f"{TMDB_BASE}/{kind}/{best['id']}", params=params, headers=headers) as r:
            if r.status != 200:
                errors.append(f"TMDB: status {r.status}")
                return None
            d = await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        errors.append(f"TMDB: ulanib bo'lmadi ({type(e).__name__})")
        return None

    date = d.get("release_date") or d.get("first_air_date") or ""
    runtime = d.get("runtime") or ((d.get("episode_run_time") or [None])[0])
    episodes = d.get("number_of_episodes") or (1 if kind == "movie" else 0)
    return {
        "matched_title": d.get("title") or d.get("name") or "",
        "year": _to_int(date[:4]) if date else None,
        "rating": round(float(d.get("vote_average") or 0), 1),
        "total_episodes": int(episodes),
        "episodes_count": int(episodes),
        "duration": _to_int(runtime),
        "status": _TMDB_STATUS.get(d.get("status") or "", "completed" if kind == "movie" else "ongoing"),
        "genres": _split_genre_names([g.get("name", "") for g in d.get("genres") or []]),
        "synopsis_en": (d.get("overview") or "").strip(),
        "image_url": None,
        "raw_names": [p.strip().lower() for g in d.get("genres") or [] for p in re.split(r"\s*&\s*|,", g.get("name", ""))],
    }


_SEASON_TAIL_RE = re.compile(
    r"[\s,:\-]*\(?\s*(?:(?:season|part|cour)\s*(\d+)|(\d+)(?:st|nd|rd|th)\s+season)\s*\)?\s*$",
    re.IGNORECASE,
)


def split_season(query: str) -> tuple[str, int | None]:
    """'Mushoku Tensei season 3' → ('Mushoku Tensei', 3). Fasl yo'q bo'lsa (query, None)."""
    q = query.strip()
    m = _SEASON_TAIL_RE.search(q)
    if not m:
        return q, None
    num = int(m.group(1) or m.group(2))
    base = q[: m.start()].strip(" ,:-")
    return (base or q), num


def _ordinal(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def _matches_season(item: dict, n: int) -> bool:
    names = " ".join(filter(None, [item.get("title"), item.get("title_english")] + [
        t.get("title", "") for t in item.get("titles") or []
    ])).lower()
    return any(k in names for k in (f"season {n}", f"{_ordinal(n)} season", f"part {n}", f" {n}"))


def _pick_best(results: list[dict], query: str, season: int | None = None) -> tuple[dict | None, bool]:
    """
    (natija, fasl_mos_keldimi) qaytaradi. Fasl so'ralgan bo'lsa shu faslga mos yozuvni
    qidiradi; topilmasa eng yaqin (odatda 1-fasl) natijani qaytaradi va False beradi.
    """
    if not results:
        return None, False
    if season and season > 1:
        for r in results:
            if _matches_season(r, season):
                return r, True
        return results[0], False
    q = query.strip().lower()
    for r in results:
        names = {(r.get("title") or "").lower(), (r.get("title_english") or "").lower()}
        if q in names:
            return r, True
    return results[0], True


def _map_status(raw: str | None) -> str:
    raw = (raw or "").lower()
    if "currently" in raw:
        return "ongoing"
    if "not yet" in raw:
        return "announced"
    return "completed"


def _parse_duration_minutes(raw: str | None) -> int | None:
    """'24 min per ep' → 24; '1 hr 55 min' → 115."""
    if not raw:
        return None
    hrs = re.search(r"(\d+)\s*hr", raw)
    mins = re.search(r"(\d+)\s*min", raw)
    total = (int(hrs.group(1)) * 60 if hrs else 0) + (int(mins.group(1)) if mins else 0)
    return total or None


def _map_genres(item: dict) -> list[str]:
    names = []
    for key in ("genres", "themes", "demographics"):
        names += [g.get("name", "") for g in item.get(key) or []]
    out: list[str] = []
    for n in names:
        mapped = _EXTRA_GENRE_MAP.get(n.lower()) or normalize_genre(n)
        if mapped in GENRES and mapped not in out:
            out.append(mapped)
    return out


def jikan_to_fields(item: dict) -> dict:
    """Jikan javobini bizning maydonlarga aylantiradi (sof funksiya — test qilish oson)."""
    year = item.get("year") or ((item.get("aired") or {}).get("prop") or {}).get("from", {}).get("year")
    episodes = item.get("episodes") or 0
    is_movie = (item.get("type") or "").lower() == "movie"
    images = (item.get("images") or {}).get("jpg") or {}
    return {
        "matched_title": item.get("title_english") or item.get("title") or "",
        "mal_id": item.get("mal_id"),
        "content_type": "movie" if is_movie else "anime",
        "year": int(year) if year else None,
        "rating": round(float(item.get("score") or 0.0), 1),
        "total_episodes": int(episodes),
        "episodes_count": int(episodes),
        "duration": _parse_duration_minutes(item.get("duration")),
        "status": _map_status(item.get("status")),
        "genres": _map_genres(item),
        "synopsis_en": (item.get("synopsis") or "").strip(),
        "image_url": images.get("large_image_url") or images.get("image_url"),
        "raw_names": [
            (g.get("name") or "").lower()
            for key in ("genres", "themes", "demographics")
            for g in item.get(key) or []
        ],
    }



# ─── Gemini ───────────────────────────────────────────────────────────

def _build_prompt(english_title: str, facts: dict | None, content_type: str) -> str:
    genre_keys = ", ".join(GENRES.keys())
    type_uz = {"anime": "anime", "movie": "kino (film)", "serial": "serial (G'arb/boshqa)", "dorama": "dorama (Osiyo serialı)"}
    base = (
        "Sen anime/kino kataloglovchi yordamchisan. Quyidagi kontent haqida "
        "FAQAT JSON qaytar (boshqa matn, markdown yo'q).\n"
        f"Kontent nomi (inglizcha): {english_title}\n"
        f"Kontent turi: {type_uz.get(content_type, content_type)}\n"
    )
    if facts:
        base += (
            f"Aniq ma'lumot: yil={facts.get('year')}, janrlar={facts.get('genres')}, "
            f"tavsif (inglizcha): {(facts.get('synopsis_en') or '')[:1500]}\n"
        )
    else:
        base += "Aniq manba topilmadi — o'zing bilganingga tayan; bilmasang null yoki bo'sh qoldir, to'qima.\n"
    mood_help = "; ".join(f"{k} ({MOOD_UZ[k]})" for k in ALLOWED_MOODS)
    base += (
        "JSON maydonlari:\n"
        "  description_uz: O'ZBEK tilida (lotin yozuvi), 2-4 gap, spoilersiz, jozibali tavsif. "
        "Inglizcha so'z yoki '(Source: ...)' kabi manba izohlarini QO'SHMA;\n"
        f"  genres: faqat shu ro'yxatdan 1-4 ta tanla: [{genre_keys}];\n"
        f"  tags: 3-6 ta teg, FAQAT shu ro'yxatdan (aynan shunday yozilishi shart): {ALLOWED_TAGS};\n"
        f"  mood: 1-3 ta kayfiyat, FAQAT shu kalitlardan: {mood_help};\n"
        "  year: chiqqan yil (son) yoki null;\n"
        "  episodes: qismlar soni (son) yoki null;\n"
        "  duration: bir qism davomiyligi daqiqada (son) yoki null;\n"
        f"  status: {STATUSES} dan biri yoki null.\n"
    )
    return base


def _gemini_err(status: int) -> str:
    return {
        400: "kalit noto'g'ri (400)", 401: "kalit noto'g'ri (401)", 403: "ruxsat yo'q (403)",
        404: "model topilmadi (404)", 429: "bepul limit tugagan (429)", 500: "server xatosi (500)",
        503: "server band (503)",
    }.get(status, f"status {status}")


_gemini_state: dict = {"model": None, "listed": [], "listed_at": 0.0}
_MODEL_HINT_RE = re.compile(r"use models/([A-Za-z0-9._\-]+)")
_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _rank_models(names: list[str]) -> list[str]:
    """generateContent'li barqaror flash modellar: yangisi oldin, 'lite' va 'preview' keyin."""
    bad = ("image", "tts", "live", "audio", "embed", "robotics", "computer", "thinking", "-exp", "learnlm")
    ok = [n for n in names if n.startswith("gemini") and "flash" in n and not any(b in n for b in bad)]

    def key(n: str):
        nums = tuple(-int(x) for x in re.findall(r"\d+", n)[:3])
        return ("preview" in n, "lite" in n, nums)

    return sorted(ok, key=key)


async def _discover_models(session: aiohttp.ClientSession, api_key: str) -> list[str]:
    """Kalitga haqiqatan ochiq modellar (6 soat keshlanadi) — model nomlari o'zgarsa ham ishlaydi."""
    import time

    if _gemini_state["listed"] and time.monotonic() - _gemini_state["listed_at"] < 6 * 3600:
        return _gemini_state["listed"]
    try:
        async with session.get(_MODELS_URL, params={"pageSize": 200}, headers={"x-goog-api-key": api_key}) as r:
            if r.status != 200:
                return []
            models = (await r.json()).get("models") or []
    except Exception:
        return []
    names = [
        m["name"].removeprefix("models/")
        for m in models
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]
    ranked = _rank_models(names)[:4]
    _gemini_state.update(listed=ranked, listed_at=time.monotonic())
    return ranked


async def _gemini_enrich(
    session: aiohttp.ClientSession, english_title: str, facts: dict | None, content_type: str, errors: list[str]
) -> dict | None:
    api_key = getattr(config, "GEMINI_API_KEY", "") or ""
    if not api_key:
        errors.append("Gemini: GEMINI_API_KEY qo'yilmagan")
        return None
    configured = [getattr(config, "GEMINI_MODEL", "gemini-flash-latest")]
    configured += [m.strip() for m in (getattr(config, "GEMINI_FALLBACK_MODELS", "") or "").split(",") if m.strip()]
    queue = deque(([_gemini_state["model"]] if _gemini_state["model"] else []) + configured)
    body = {
        "contents": [{"parts": [{"text": _build_prompt(english_title, facts, content_type)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    }
    tried: set[str] = set()
    discovered = False
    last = None
    while queue and len(tried) < 8:
        model = queue.popleft()
        if not model or model in tried:
            if not queue and not discovered:
                discovered = True
                queue.extend(await _discover_models(session, api_key))
            continue
        tried.add(model)
        try:
            async with session.post(
                GEMINI_URL.format(model=model), headers={"x-goog-api-key": api_key}, json=body
            ) as resp:
                status = resp.status
                err_body = (await resp.text()) if status != 200 else ""
                payload = await resp.json() if status == 200 else None
            if status != 200:
                last = f"{model}: {_gemini_err(status)}"
                logger.warning("Gemini %s status=%s %s", model, status, err_body[:200])
                if status in (400, 401, 403):
                    break  # kalit muammosi — boshqa model yordam bermaydi
                hint = _MODEL_HINT_RE.search(err_body) if status == 404 else None
                if hint and hint.group(1) not in tried:
                    queue.appendleft(hint.group(1))  # Google o'zi yangi model nomini aytdi
            else:
                text = payload["candidates"][0]["content"]["parts"][0]["text"]
                text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
                data = json.loads(text)
                if isinstance(data, dict):
                    _gemini_state["model"] = model  # ishlagan modelni eslab qolamiz
                    return data
                last = f"{model}: noto'g'ri javob"
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last = f"{model}: ulanib bo'lmadi ({type(e).__name__})"
        except Exception as e:  # JSON/tuzilma xatosi
            last = f"{model}: javob o'qilmadi ({type(e).__name__})"
            logger.warning("Gemini parse xato", exc_info=True)
        if not queue and not discovered:
            discovered = True
            queue.extend(await _discover_models(session, api_key))
    errors.append(f"Gemini: {last}")
    return None


# ─── Tarjima zaxirasi (Gemini ishlamasa tavsifni o'zbekchaga o'giradi) ──

_SOURCE_NOTE_RE = re.compile(r"\s*[\(\[]\s*(?:Source|Written by)[^\)\]]*[\)\]]", re.IGNORECASE)


def clean_synopsis(text: str | None) -> str:
    """'(Source: Crunchyroll)', '[Written by MAL Rewrite]' kabi izohlarni olib tashlaydi."""
    return _SOURCE_NOTE_RE.sub("", text or "").strip()


def _chunks(text: str, limit: int = 900) -> list[str]:
    out, cur = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if cur and len(cur) + len(sentence) + 1 > limit:
            out.append(cur)
            cur = ""
        cur = f"{cur} {sentence}".strip()
    if cur:
        out.append(cur)
    return out


async def _translate_uz(session: aiohttp.ClientSession, text: str, errors: list[str]) -> str | None:
    """Inglizcha → o'zbekcha (Google Tarjima'ning ochiq endpointi, kalitsiz)."""
    url = "https://translate.googleapis.com/translate_a/single"
    parts: list[str] = []
    try:
        for chunk in _chunks(text):
            async with session.post(
                url, params={"client": "gtx", "sl": "en", "tl": "uz", "dt": "t"}, data={"q": chunk}
            ) as r:
                if r.status != 200:
                    errors.append(f"Tarjima: status {r.status}")
                    return None
                data = await r.json(content_type=None)
            parts.append("".join(seg[0] for seg in data[0] if seg and seg[0]))
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        errors.append(f"Tarjima: ulanib bo'lmadi ({type(e).__name__})")
        return None
    except Exception as e:
        errors.append(f"Tarjima: javob o'qilmadi ({type(e).__name__})")
        return None
    return " ".join(p.strip() for p in parts if p.strip()) or None


# ─── Kayfiyat va teglar (botning o'z lug'ati) ────────────────────────

def _genre_english(key: str) -> str:
    """'SliceOfLife' kabi janr yorlig'ini 'slice of life' ga aylantiradi (heuristika uchun)."""
    label = re.sub(r"[^A-Za-z ]", "", str(GENRES.get(key, key))).strip()
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label).lower()


def _clean_moods(values, limit: int = 3) -> list[str]:
    out: list[str] = []
    for v in values or []:
        m = normalize_mood(str(v))
        if m and m not in out:
            out.append(m)
    return out[:limit]


def _clean_tags(values, limit: int = 6) -> list[str]:
    out: list[str] = []
    for v in values or []:
        t = str(v).strip().lower()
        if t in ALLOWED_TAGS and t not in out:
            out.append(t)
    return out[:limit]


def derive_mood_tags(raw_names: list[str]) -> tuple[list[str], list[str]]:
    """
    AI ishlamaganda: manbadagi janr/mavzu nomlaridan (inglizcha) kayfiyat va teglarni chiqaradi.
    Masalan {"action","fantasy"} → mood ["action","fantasy"], teglar ["adventure", ...].
    """
    names = {n.strip().lower() for n in raw_names if n}
    tags = [t for t in ALLOWED_TAGS if t in names]
    scored = []
    for mood, cfg in MOOD_MAP.items():
        score = len(names & set(cfg["genres"])) + len(names & set(cfg["tags"]))
        if score:
            scored.append((score, mood))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:3]], tags[:6]


def _clean_list(values, allowed: list[str] | None = None, limit: int = 5) -> list[str]:
    out: list[str] = []
    for v in values or []:
        v = str(v).strip()
        if not v:
            continue
        if allowed is not None:
            v = normalize_genre(v) if allowed is GENRES else v.lower()
            if v not in allowed:
                continue
        if v not in out:
            out.append(v)
    return out[:limit]


# ─── Asosiy funksiya ──────────────────────────────────────────────────

async def _find_anime_facts(session, english_title: str, content_type: str, errors: list[str]):
    """(facts, eslatma, manba). Jikan → AniList. Kino uchun faqat nomi aniq mos kelsa qabul qilinadi."""
    base_query, season = split_season(english_title)
    variants = list(dict.fromkeys([english_title.strip(), base_query]))
    for source, search in (("MyAnimeList", _jikan_search), ("AniList", _anilist_search)):
        results: list[dict] = []
        err = None
        for variant in variants:
            results, err = await search(session, variant)
            if results:
                break
            await asyncio.sleep(0.3)
        if err and not results:
            errors.append(f"{source}: {err}")
        best, season_ok = _pick_best(results, base_query, season)
        if best is None:
            continue
        if content_type == "movie":
            names = {_norm(best.get("title")), _norm(best.get("title_english"))}
            if _norm(base_query) not in names:
                continue  # kino uchun taxminiy moslik xavfli (boshqa kontent chiqib qolishi mumkin)
        facts = jikan_to_fields(best)
        note = ""
        if not season_ok:
            note = (f"{season}-fasl {source}'da topilmadi: janr/tavsif umumiy serialdan olindi, "
                    "yil/reyting/qismlarni qo'lda kiriting.")
            for k in ("year", "rating", "total_episodes", "episodes_count", "duration"):
                facts[k] = None if k in ("year", "duration") else 0
        return facts, note, source
    return None, "", ""


async def build_content_info(english_title: str, content_type: str = "anime") -> dict:
    """
    Inglizcha nom va (admin tanlagan) tur bo'yicha ma'lumot yig'adi.
    Hech narsa topilmasa ham dict qaytaradi; sabablari `errors` da.
    """
    if content_type not in CONTENT_TYPES:
        content_type = "anime"
    errors: list[str] = []
    sources: list[str] = []
    facts: dict | None = None
    note = ""

    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT, headers=HTTP_HEADERS) as session:
        try:
            if content_type in ("anime", "movie"):
                facts, note, src = await _find_anime_facts(session, english_title, content_type, errors)
                if facts:
                    sources.append(src)
            if facts is None and content_type != "anime":
                facts = await _tmdb_facts(session, english_title, content_type, errors)
                if facts:
                    sources.append("TMDB")
        except Exception:
            logger.warning("manba qidirishda xato", exc_info=True)
            errors.append("Manbalarni qidirishda ichki xato")
        if facts and facts.get("synopsis_en"):
            facts["synopsis_en"] = clean_synopsis(facts["synopsis_en"])
        ai = await _gemini_enrich(session, english_title, facts, content_type, errors)
        if ai:
            sources.append("Gemini AI")
        translated = None
        if not (ai or {}).get("description_uz") and facts and facts.get("synopsis_en"):
            # Gemini ishlamadi — tavsif baribir o'zbekcha bo'lsin
            translated = await _translate_uz(session, facts["synopsis_en"], errors)
            if translated:
                sources.append("Google Tarjima")

    ai = ai or {}
    facts = facts or {}
    have_facts = bool(facts) and not note

    genres = facts.get("genres") or _clean_list(ai.get("genres"), GENRES, 4)
    year = facts.get("year") or (None if note else _to_int(ai.get("year")))
    episodes = facts.get("episodes_count") or (0 if note else (_to_int(ai.get("episodes")) or 0))
    if content_type == "movie" and not episodes:
        episodes = 1
    duration = facts.get("duration") or (None if note else _to_int(ai.get("duration")))
    status = facts.get("status") if have_facts else None
    if not status:
        status = ai.get("status") if (ai.get("status") in STATUSES and not note) else "ongoing"
    # Tavsif faqat o'zbekcha: Gemini yoki tarjima. Ikkalasi ham bo'lmasa bo'sh (inglizcha qoldirilmaydi).
    desc = (ai.get("description_uz") or translated or "").strip()

    # Kayfiyat/teglar — botning o'z lug'atidan (qidiruv va tavsiyalar topishi uchun)
    raw_names = list(facts.get("raw_names") or []) or [_genre_english(g) for g in genres]
    d_moods, d_tags = derive_mood_tags(raw_names)
    moods = _clean_moods(ai.get("mood")) or d_moods
    tags = _clean_tags(ai.get("tags"))
    for t in d_tags:
        if t not in tags and len(tags) < 6:
            tags.append(t)

    return {
        "content_type": content_type,
        "desc": desc[:1500],
        "genres": genres,
        "tags": tags,
        "mood": moods,
        "year": year,
        "rating": facts.get("rating") or 0.0,
        "total_episodes": episodes,
        "episodes_count": episodes,
        "duration": duration,
        "status": status,
        "image_url": facts.get("image_url"),
        "matched_title": facts.get("matched_title") or "",
        "note": note,
        "errors": errors,
        "sources": sources,
    }
