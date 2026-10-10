"""
utils/ai_anime.py — kontent ma'lumotlarini avtomatik to'plash (bepul).

Manbalar:
  1) Jikan API (MyAnimeList, kalit kerak emas, bepul) — aniq faktlar:
     yil, reyting, qismlar soni, davomiylik, status, janrlar, inglizcha tavsif.
  2) Google Gemini (bepul tarif, GEMINI_API_KEY kerak) — tavsifni o'zbekchaga
     o'giradi, teg va mood tanlaydi. Kalit bo'lmasa — faqat Jikan ishlaydi.

Natija: `AIResult` dict'i; kalitlari `_save_anime` kutgan FSM kalitlariga mos.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

import aiohttp

from data import config
from handlers.genres import GENRES, normalize_genre

logger = logging.getLogger(__name__)

JIKAN_SEARCH_URL = "https://api.jikan.moe/v4/anime"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=25)

ALLOWED_MOODS = [
    "dark", "emotional", "funny", "relaxing", "intense",
    "wholesome", "mysterious", "inspiring", "romantic", "thrilling",
]
CONTENT_TYPES = ["anime", "movie", "serial", "dorama"]

# Jikan janr nomlari GENRE_ALIASES da bo'lmaganlari
_EXTRA_GENRE_MAP = {
    "suspense": "Triller",
    "supernatural": "G'ayritabiiy",
    "super power": "G'ayritabiiy",
    "gore": "Qo'rqinchli",
}


# ─── Jikan ────────────────────────────────────────────────────────────

async def _jikan_search(session: aiohttp.ClientSession, query: str) -> list[dict]:
    params = {"q": query, "limit": 5, "sfw": "true"}
    for attempt in range(2):
        async with session.get(JIKAN_SEARCH_URL, params=params) as resp:
            if resp.status == 429 and attempt == 0:
                await asyncio.sleep(1.5)  # Jikan rate-limit — bir marta qayta urinamiz
                continue
            if resp.status != 200:
                logger.warning("Jikan status=%s", resp.status)
                return []
            payload = await resp.json()
            return payload.get("data") or []
    return []


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
    }


# ─── Gemini ───────────────────────────────────────────────────────────

def _build_prompt(english_title: str, facts: dict | None) -> str:
    genre_keys = ", ".join(GENRES.keys())
    base = (
        "Sen anime/kino kataloglovchi yordamchisan. Quyidagi kontent haqida "
        "FAQAT JSON qaytar (boshqa matn, markdown yo'q).\n"
        f"Kontent nomi (inglizcha): {english_title}\n"
    )
    if facts:
        base += (
            f"Aniq ma'lumot (MyAnimeList): yil={facts.get('year')}, "
            f"janrlar={facts.get('genres')}, tavsif (inglizcha): {facts.get('synopsis_en')[:1500]}\n"
        )
    else:
        base += "Ma'lumot topilmadi — o'zing bilganingga tayan; bilmasang bo'sh qoldir.\n"
    base += (
        "JSON maydonlari:\n"
        "  description_uz: o'zbek tilida (lotin), 2-4 gap, spoilersiz, jozibali tavsif;\n"
        f"  genres: faqat shu ro'yxatdan 1-4 ta tanla: [{genre_keys}];\n"
        "  tags: 3-5 ta qisqa inglizcha kichik harfli teg (masalan revenge, survival);\n"
        f"  mood: shu ro'yxatdan 1-3 ta: {ALLOWED_MOODS};\n"
        f"  content_type: {CONTENT_TYPES} dan biri;\n"
        "  year: son yoki null.\n"
    )
    return base


async def _gemini_enrich(session: aiohttp.ClientSession, english_title: str, facts: dict | None) -> dict | None:
    api_key = getattr(config, "GEMINI_API_KEY", "") or ""
    if not api_key:
        return None
    url = GEMINI_URL.format(model=getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"))
    body = {
        "contents": [{"parts": [{"text": _build_prompt(english_title, facts)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    }
    try:
        async with session.post(url, headers={"x-goog-api-key": api_key}, json=body) as resp:
            if resp.status != 200:
                logger.warning("Gemini status=%s body=%s", resp.status, (await resp.text())[:300])
                return None
            payload = await resp.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        logger.warning("Gemini xato", exc_info=True)
        return None


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

async def build_content_info(english_title: str) -> dict:
    """
    Inglizcha nom bo'yicha ma'lumotlarni yig'adi.

    Qaytaradi dict (FSM kalitlari bilan):
      content_type, desc, genres, tags, mood, year, rating, total_episodes,
      episodes_count, duration, status, image_url, matched_title, sources (list[str])
    Hech narsa topilmasa ham dict qaytaradi (bo'sh maydonlar bilan) — admin tuzatadi.
    """
    facts: dict | None = None
    sources: list[str] = []
    note = ""
    base_query, season = split_season(english_title)
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        try:
            # Avval to'liq nom, topilmasa fasl qo'shimchasiz nom bilan qidiramiz
            results: list[dict] = []
            for variant in dict.fromkeys([english_title.strip(), base_query]):
                results = await _jikan_search(session, variant)
                if results:
                    break
                await asyncio.sleep(0.4)
            best, season_ok = _pick_best(results, base_query, season)
            if best:
                facts = jikan_to_fields(best)
                sources.append("MyAnimeList")
                if not season_ok:
                    # Boshqa fasl ma'lumoti — raqamlarni noto'g'ri qo'ymaymiz
                    note = (f"{season}-fasl MyAnimeList'da topilmadi: janr/tavsif umumiy serialdan olindi, "
                            "yil/reyting/qismlarni qo'lda kiriting.")
                    for k in ("year", "rating", "total_episodes", "episodes_count", "duration"):
                        facts[k] = None if k in ("year", "duration") else 0
        except Exception:
            logger.warning("Jikan xato", exc_info=True)
        ai = await _gemini_enrich(session, english_title, facts)
        if ai:
            sources.append("Gemini AI")

    ai = ai or {}
    facts = facts or {}

    genres = facts.get("genres") or _clean_list(ai.get("genres"), GENRES, 4)
    ctype = facts.get("content_type") or (ai.get("content_type") if ai.get("content_type") in CONTENT_TYPES else "anime")
    year = facts.get("year") or (int(ai["year"]) if str(ai.get("year") or "").isdigit() else None)
    desc = ai.get("description_uz") or facts.get("synopsis_en") or ""

    return {
        "content_type": ctype,
        "desc": desc.strip()[:1500],
        "genres": genres,
        "tags": _clean_list(ai.get("tags"), None, 5),
        "mood": _clean_list(ai.get("mood"), ALLOWED_MOODS, 3),
        "year": year,
        "rating": facts.get("rating") or 0.0,
        "total_episodes": facts.get("total_episodes") or 0,
        "episodes_count": facts.get("episodes_count") or 0,
        "duration": facts.get("duration"),
        "status": (facts.get("status") if not note else None) or "ongoing",
        "image_url": facts.get("image_url"),
        "matched_title": facts.get("matched_title") or "",
        "note": note,
        "sources": sources,
    }
