"""
Kaworai Pro — AI Recommendation Engine
Tashqi AI API ishlatilmaydi. Weighted scoring + taste profile asosida ishlaydi.

ALGORITM:
  score = (genre_match × 0.35)
        + (tag_match   × 0.25)
        + (mood_match  × 0.20)
        + (rating_norm × 0.12)
        + (popularity  × 0.05)
        + (year_bonus  × 0.03)
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Anime, UserWatchHistory, UserTasteProfile, RelatedContent, ViewRecord
)


# ═══════════════════════════════════════════════════════════
#  MOOD → TAGS/GENRES xaritasi
# ═══════════════════════════════════════════════════════════

MOOD_MAP: dict[str, dict] = {
    # Kalit sozlar → tags va genres
    "sad": {
        "tags":   ["emotional", "tragedy", "loss", "grief", "tearjerker"],
        "genres": ["drama", "slice of life", "romance"],
        "boost_genres": ["drama"]
    },
    "romantic": {
        "tags":   ["romance", "love", "wholesome", "heartwarming", "couple"],
        "genres": ["romance", "slice of life", "shoujo"],
        "boost_genres": ["romance"]
    },
    "dark": {
        "tags":   ["dark", "psychological", "horror", "gore", "survival", "dystopia"],
        "genres": ["psychological", "horror", "thriller", "seinen"],
        "boost_genres": ["psychological", "thriller"]
    },
    "motivational": {
        "tags":   ["redemption", "growth", "sports", "underdog", "determination"],
        "genres": ["sports", "action", "shounen"],
        "boost_genres": ["sports", "shounen"]
    },
    "action": {
        "tags":   ["battle", "fight", "war", "revenge", "power"],
        "genres": ["action", "adventure", "shounen"],
        "boost_genres": ["action"]
    },
    "funny": {
        "tags":   ["comedy", "parody", "wholesome", "cute"],
        "genres": ["comedy", "slice of life"],
        "boost_genres": ["comedy"]
    },
    "mystery": {
        "tags":   ["mystery", "detective", "plot twist", "conspiracy"],
        "genres": ["mystery", "thriller", "psychological"],
        "boost_genres": ["mystery"]
    },
    "chill": {
        "tags":   ["wholesome", "iyashikei", "relaxing", "cute", "slice of life"],
        "genres": ["slice of life", "comedy"],
        "boost_genres": ["slice of life"]
    },
    "fantasy": {
        "tags":   ["magic", "isekai", "fantasy world", "adventure"],
        "genres": ["fantasy", "adventure", "isekai"],
        "boost_genres": ["fantasy"]
    },
    "scary": {
        "tags":   ["horror", "gore", "supernatural", "monsters", "thriller"],
        "genres": ["horror", "psychological"],
        "boost_genres": ["horror"]
    },
}

# Matn → mood aniqlash uchun kalit so'zlar
TEXT_TO_MOOD: dict[str, list[str]] = {
    "sad":         ["sad", "xafa", "g'amgin", "yig'lay", "ko'z yosh", "depressed", "cry", "emo"],
    "romantic":    ["romantic", "sevgi", "love", "muhabbat", "sevaman", "romance", "heart"],
    "dark":        ["dark", "qorong'u", "qo'rqinchli", "psychological", "og'ir", "heavy"],
    "motivational":["motivational", "ilhomlantiruvchi", "kuch", "sport", "fight", "motivate"],
    "action":      ["action", "jangari", "fight", "battle", "war", "explosion"],
    "funny":       ["funny", "kulgi", "kulgili", "comedy", "ha-ha", "lol", "humor"],
    "mystery":     ["mystery", "sirli", "detective", "jumboq", "puzzle"],
    "chill":       ["chill", "yengil", "relax", "easy", "dam olish", "tinch"],
    "fantasy":     ["fantasy", "sehr", "magic", "isekai", "boshqa dunyo"],
    "scary":       ["scary", "qo'rqinchli", "horror", "dahshat"],
}


def detect_mood_from_text(text: str) -> list[str]:
    """
    Foydalanuvchi matni asosida mood(lar) aniqlaydi.
    'men xafa his qilyapman' → ['sad']
    """
    text_lower = text.lower()
    detected = []
    for mood, keywords in TEXT_TO_MOOD.items():
        for kw in keywords:
            if kw in text_lower:
                detected.append(mood)
                break
    return detected or ["chill"]   # default: chill


def mood_to_filters(moods: list[str]) -> dict:
    """Mood ro'yxatini tags va genres filtrlariga aylantiradi."""
    all_tags   = []
    all_genres = []
    for mood in moods:
        if mood in MOOD_MAP:
            all_tags.extend(MOOD_MAP[mood]["tags"])
            all_genres.extend(MOOD_MAP[mood]["genres"])
    return {
        "tags":   list(set(all_tags)),
        "genres": list(set(all_genres)),
    }


# ═══════════════════════════════════════════════════════════
#  WEIGHTED SCORING ENGINE
# ═══════════════════════════════════════════════════════════

def compute_score(
    anime: Anime,
    user_genres:  dict[str, int],   # {"action": 5, "drama": 3}
    user_tags:    dict[str, int],   # {"dark": 4}
    user_moods:   dict[str, int],   # {"dark": 2}
    target_genres: list[str] | None = None,   # mood/filter dan kelgan
    target_tags:   list[str] | None = None,
    target_moods:  list[str] | None = None,
) -> float:
    """
    Bir anime uchun relevance score hisoblab beradi.
    Score 0.0 — 10.0 oralig'ida bo'ladi.
    """
    anime_genres = [g.lower() for g in (anime.genres or [])]
    anime_tags   = [t.lower() for t in (anime.tags   or [])]
    anime_moods  = [m.lower() for m in (anime.mood   or [])]

    # ── 1. Genre match (0–3.5) ──
    genre_score = 0.0
    total_user_genre_views = max(sum(user_genres.values()), 1)
    for g in anime_genres:
        if g in user_genres:
            genre_score += user_genres[g] / total_user_genre_views
    if target_genres:
        matched = len(set(anime_genres) & set(target_genres))
        genre_score += matched * 0.4
    genre_score = min(genre_score, 1.0) * 3.5

    # ── 2. Tag match (0–2.5) ──
    tag_score = 0.0
    total_user_tag_views = max(sum(user_tags.values()), 1)
    for t in anime_tags:
        if t in user_tags:
            tag_score += user_tags[t] / total_user_tag_views
    if target_tags:
        matched = len(set(anime_tags) & set(target_tags))
        tag_score += matched * 0.3
    tag_score = min(tag_score, 1.0) * 2.5

    # ── 3. Mood match (0–2.0) ──
    mood_score = 0.0
    total_user_mood_views = max(sum(user_moods.values()), 1)
    for m in anime_moods:
        if m in user_moods:
            mood_score += user_moods[m] / total_user_mood_views
    if target_moods:
        matched = len(set(anime_moods) & set(target_moods))
        mood_score += matched * 0.4
    mood_score = min(mood_score, 1.0) * 2.0

    # ── 4. Rating normalize (0–1.2) ──
    rating_score = (anime.rating / 10.0) * 1.2

    # ── 5. Popularity (0–0.5) ──
    pop_score = min(anime.popularity_score / 100.0, 1.0) * 0.5

    # ── 6. Year bonus (0–0.3) ──
    year_score = 0.0
    if anime.year and anime.year >= 2020:
        year_score = 0.3
    elif anime.year and anime.year >= 2015:
        year_score = 0.15

    total = genre_score + tag_score + mood_score + rating_score + pop_score + year_score
    return round(total, 4)


# ═══════════════════════════════════════════════════════════
#  TASTE PROFILE YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════

async def get_or_create_taste_profile(
    session: AsyncSession, user_id: int
) -> UserTasteProfile:
    result = await session.execute(
        select(UserTasteProfile).where(UserTasteProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        profile = UserTasteProfile(
            user_id=user_id,
            fav_genres={},
            fav_tags={},
            fav_moods={},
        )
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return profile


async def update_taste_profile(
    session: AsyncSession, user_id: int, anime: Anime
) -> None:
    """
    User kontent ko'rganda taste profilini yangilaydi.
    Har bir genre/tag/mood uchun counter oshiriladi.
    """
    profile = await get_or_create_taste_profile(session, user_id)

    # Genres
    g_counter = dict(profile.fav_genres or {})
    for g in (anime.genres or []):
        g_lower = g.lower()
        g_counter[g_lower] = g_counter.get(g_lower, 0) + 1

    # Tags
    t_counter = dict(profile.fav_tags or {})
    for t in (anime.tags or []):
        t_lower = t.lower()
        t_counter[t_lower] = t_counter.get(t_lower, 0) + 1

    # Moods
    m_counter = dict(profile.fav_moods or {})
    for m in (anime.mood or []):
        m_lower = m.lower()
        m_counter[m_lower] = m_counter.get(m_lower, 0) + 1

    # Content type
    type_counter = {}
    history = await session.execute(
        select(UserWatchHistory)
        .where(UserWatchHistory.user_id == user_id)
        .limit(20)
    )
    for hw in history.scalars().all():
        a = await session.get(Anime, hw.anime_id)
        if a:
            ct = a.content_type or "anime"
            type_counter[ct] = type_counter.get(ct, 0) + 1
    fav_type = max(type_counter, key=type_counter.get) if type_counter else "anime"

    profile.fav_genres = g_counter
    profile.fav_tags   = t_counter
    profile.fav_moods  = m_counter
    profile.fav_type   = fav_type
    await session.commit()


def build_identity_label(profile: UserTasteProfile) -> str:
    """
    'Sen dark anime muxlisisan!' kabi identity label yaratadi.
    Psixologik personalizatsiya uchun.
    """
    if not profile or not profile.fav_genres:
        return "🎌 Anime muxlisi"

    genres = dict(profile.fav_genres or {})
    tags   = dict(profile.fav_tags   or {})

    top_genre = max(genres, key=genres.get) if genres else None
    top_tag   = max(tags,   key=tags.get)   if tags   else None
    fav_type  = profile.fav_type or "anime"

    type_labels = {
        "anime":  "anime",
        "movie":  "kino",
        "serial": "serial",
        "dorama": "dorama",
    }

    tag_labels = {
        "dark":          "🌑 Qorong'u",
        "psychological": "🧠 Psixologik",
        "romance":       "💕 Romantik",
        "action":        "⚔️ Jangari",
        "comedy":        "😂 Kulgili",
        "supernatural":  "👻 G'ayritabiiy",
        "sports":        "🏆 Sport",
        "horror":        "😱 Qo'rqinchli",
        "wholesome":     "🌸 Iliq qalbli",
        "survival":      "🔥 Omon qolish",
        "emotional":     "💔 Hissiy",
        "mystery":       "🔍 Sirli",
    }

    t_label = tag_labels.get(top_tag, top_tag) if top_tag else None
    type_str = type_labels.get(fav_type, fav_type)

    if t_label and top_genre:
        return f"{t_label} {top_genre} {type_str} muxlisisan! 🔥"
    elif top_genre:
        return f"🎯 Sen {top_genre} {type_str} muxlisisan!"
    return f"🎌 {type_str.capitalize()} muxlisi"


# ═══════════════════════════════════════════════════════════
#  ASOSIY RECOMMENDATION FUNKSIYALAR
# ═══════════════════════════════════════════════════════════

async def get_recommendations(
    session: AsyncSession,
    user_id: int,
    content_type: str | None = None,   # filter: anime|movie|serial|dorama
    mood_text: str | None = None,       # user yozgan matn
    target_moods: list[str] | None = None,
    limit: int = 10,
    is_pro: bool = False,
) -> list[dict]:
    """
    Asosiy recommendation funksiyasi.
    User taste profile + mood + weighted scoring asosida ishlaydi.
    """
    # 1. Taste profile olish
    profile = await get_or_create_taste_profile(session, user_id)
    user_genres = dict(profile.fav_genres or {})
    user_tags   = dict(profile.fav_tags   or {})
    user_moods  = dict(profile.fav_moods  or {})

    # 2. Mood aniqlash
    t_genres, t_tags, t_moods = [], [], []
    if mood_text:
        detected = detect_mood_from_text(mood_text)
        filters  = mood_to_filters(detected)
        t_genres = filters["genres"]
        t_tags   = filters["tags"]
        t_moods  = detected
    elif target_moods:
        filters  = mood_to_filters(target_moods)
        t_genres = filters["genres"]
        t_tags   = filters["tags"]
        t_moods  = target_moods

    # 3. Ko'rilgan kontentlar IDlari (exclude qilish uchun)
    watched_result = await session.execute(
        select(UserWatchHistory.anime_id).where(
            UserWatchHistory.user_id == user_id
        )
    )
    watched_ids = set(row[0] for row in watched_result.fetchall())

    # 4. Barcha kontentni olish (filter bilan)
    query = select(Anime)
    if content_type:
        query = query.where(Anime.content_type == content_type)
    if not is_pro:
        query = query.where(Anime.is_pro_locked == False)

    result = await session.execute(query)
    all_content = result.scalars().all()

    # 5. Scoring
    scored = []
    for anime in all_content:
        if anime.id in watched_ids:
            continue
        score = compute_score(
            anime, user_genres, user_tags, user_moods,
            t_genres, t_tags, t_moods
        )
        scored.append((anime, score))

    # 6. Sort va limit
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:limit]

    return [_anime_to_dict(a, score=s) for a, s in top]


async def get_trending(
    session: AsyncSession,
    content_type: str | None = None,
    limit: int = 10,
    is_pro: bool = False,
) -> list[dict]:
    """
    Trending: so'nggi 7 kunda eng ko'p ko'rilgan kontentlar.
    """
    from datetime import datetime, timedelta
    week_ago = datetime.utcnow() - timedelta(days=7)

    subq = (
        select(ViewRecord.anime_id, func.count(ViewRecord.id).label("cnt"))
        .where(ViewRecord.viewed_at >= week_ago)
        .group_by(ViewRecord.anime_id)
        .order_by(func.count(ViewRecord.id).desc())
        .limit(limit * 2)
        .subquery()
    )

    query = (
        select(Anime, subq.c.cnt)
        .join(subq, Anime.id == subq.c.anime_id)
    )
    if content_type:
        query = query.where(Anime.content_type == content_type)
    if not is_pro:
        query = query.where(Anime.is_pro_locked == False)

    result = await session.execute(query)
    rows = result.fetchall()[:limit]
    return [_anime_to_dict(a, extra={"trend_views": cnt}) for a, cnt in rows]


async def get_top_rated(
    session: AsyncSession,
    content_type: str | None = None,
    limit: int = 10,
    is_pro: bool = False,
) -> list[dict]:
    """Top rated — eng yuqori reytingli kontentlar."""
    query = (
        select(Anime)
        .where(Anime.rating_count >= 3)   # kamida 3 ovoz bo'lsin
        .order_by(Anime.rating.desc())
    )
    if content_type:
        query = query.where(Anime.content_type == content_type)
    if not is_pro:
        query = query.where(Anime.is_pro_locked == False)

    result = await session.execute(query.limit(limit))
    return [_anime_to_dict(a) for a in result.scalars().all()]


async def get_rising(
    session: AsyncSession,
    content_type: str | None = None,
    limit: int = 10,
    is_pro: bool = False,
) -> list[dict]:
    """
    Rising: so'nggi 3 kunda tez o'sayotgan kontentlar.
    Views o'sish tezligi bo'yicha sort.
    """
    from datetime import datetime, timedelta
    three_days_ago = datetime.utcnow() - timedelta(days=3)

    subq = (
        select(ViewRecord.anime_id, func.count(ViewRecord.id).label("recent_cnt"))
        .where(ViewRecord.viewed_at >= three_days_ago)
        .group_by(ViewRecord.anime_id)
        .order_by(func.count(ViewRecord.id).desc())
        .limit(limit * 2)
        .subquery()
    )

    query = (
        select(Anime, subq.c.recent_cnt)
        .join(subq, Anime.id == subq.c.anime_id)
    )
    if content_type:
        query = query.where(Anime.content_type == content_type)
    if not is_pro:
        query = query.where(Anime.is_pro_locked == False)

    result = await session.execute(query)
    rows = result.fetchall()[:limit]
    return [_anime_to_dict(a, extra={"rising_views": cnt}) for a, cnt in rows]


async def get_hidden_gems(
    session: AsyncSession,
    content_type: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """
    Hidden Gems: kam mashhur lekin yuqori reytingli kontentlar.
    rating >= 8.0 va views <= 1000
    """
    query = (
        select(Anime)
        .where(Anime.rating >= 8.0)
        .where(Anime.views <= 1000)
        .where(Anime.rating_count >= 2)
        .order_by(Anime.rating.desc())
    )
    if content_type:
        query = query.where(Anime.content_type == content_type)

    result = await session.execute(query.limit(limit))
    return [_anime_to_dict(a) for a in result.scalars().all()]


async def get_related_content(
    session: AsyncSession,
    anime_id: int,
    limit: int = 6,
    is_pro: bool = False,
) -> list[dict]:
    """
    Related content: sequel/prequel/similar kontentlar.
    'Buni ko'rganlar buni ham ko'rgan' logikasi ham qo'shilgan.
    """
    results = []

    # 1. Bevosita related (DB dan)
    rel_query = (
        select(RelatedContent, Anime)
        .join(Anime, RelatedContent.related_id == Anime.id)
        .where(RelatedContent.anime_id == anime_id)
    )
    rel_result = await session.execute(rel_query)
    for rel, anime in rel_result.fetchall():
        if not is_pro and anime.is_pro_locked:
            continue
        results.append(_anime_to_dict(anime, extra={"relation": rel.relation_type}))

    # 2. "Buni ko'rganlar buni ham ko'rgan"
    if len(results) < limit:
        # Shu animeni ko'rgan userlar topiladi
        watchers = await session.execute(
            select(UserWatchHistory.user_id)
            .where(UserWatchHistory.anime_id == anime_id)
            .limit(50)
        )
        watcher_ids = [r[0] for r in watchers.fetchall()]

        if watcher_ids:
            # O'sha userlar boshqa nima ko'rgan?
            also_watched = await session.execute(
                select(UserWatchHistory.anime_id, func.count().label("cnt"))
                .where(
                    UserWatchHistory.user_id.in_(watcher_ids),
                    UserWatchHistory.anime_id != anime_id
                )
                .group_by(UserWatchHistory.anime_id)
                .order_by(func.count().desc())
                .limit(limit * 2)
            )
            existing_ids = {r["id"] for r in results if "id" in r}
            for row in also_watched.fetchall():
                if len(results) >= limit:
                    break
                if row[0] in existing_ids:
                    continue
                a = await session.get(Anime, row[0])
                if a and (is_pro or not a.is_pro_locked):
                    results.append(_anime_to_dict(a, extra={"relation": "also_watched"}))

    return results[:limit]


async def get_next_recommendation(
    session: AsyncSession,
    user_id: int,
    current_anime_id: int,
    is_pro: bool = False,
) -> dict | None:
    """
    Next hook: user kontent tugagach keyingi tavsiya.
    1. Sequel/prequel bor bo'lsa — avval o'sha
    2. Yo'q bo'lsa — recommendation engine
    """
    # Sequel bor?
    rel = await session.execute(
        select(RelatedContent, Anime)
        .join(Anime, RelatedContent.related_id == Anime.id)
        .where(
            RelatedContent.anime_id == current_anime_id,
            RelatedContent.relation_type == "sequel"
        )
        .limit(1)
    )
    row = rel.fetchone()
    if row:
        _, anime = row
        if is_pro or not anime.is_pro_locked:
            return _anime_to_dict(anime, extra={"reason": "sequel"})

    # Yo'q bo'lsa — personalized
    recs = await get_recommendations(
        session, user_id, limit=1, is_pro=is_pro
    )
    if recs:
        recs[0]["reason"] = "personalized"
        return recs[0]
    return None


async def get_smart_continue(
    session: AsyncSession,
    user_id: int,
) -> list[dict]:
    """
    Smart Continue: user oxirgi to'xtagan joyidan davom ettira olsin.
    Tugamagan kontentlarni qaytaradi.
    """
    result = await session.execute(
        select(UserWatchHistory, Anime)
        .join(Anime, UserWatchHistory.anime_id == Anime.id)
        .where(
            UserWatchHistory.user_id == user_id,
            UserWatchHistory.is_completed == False,
            UserWatchHistory.last_episode > 0,
        )
        .order_by(UserWatchHistory.watched_at.desc())
        .limit(5)
    )
    items = []
    for hw, anime in result.fetchall():
        d = _anime_to_dict(anime)
        d["last_episode"] = hw.last_episode
        d["resume_from"]  = hw.last_episode + 1
        items.append(d)
    return items


async def get_pro_locked_teaser(
    session: AsyncSession,
    content_type: str | None = None,
    limit: int = 3,
) -> list[dict]:
    """
    Pro-locked kontentlarni teaser sifatida ko'rsatadi.
    Oddiy userlarga 'yopiq' belgisi bilan chiqadi — FOMO yaratish uchun.
    """
    query = select(Anime).where(Anime.is_pro_locked == True)
    if content_type:
        query = query.where(Anime.content_type == content_type)
    query = query.order_by(Anime.rating.desc()).limit(limit)

    result = await session.execute(query)
    items = []
    for anime in result.scalars().all():
        d = _anime_to_dict(anime)
        d["locked"] = True
        # Tavsifni yashirish
        d["description"] = "🔒 Bu kontent Kaworai Pro foydalanuvchilariga ochiq..."
        items.append(d)
    return items


# ═══════════════════════════════════════════════════════════
#  POPULARITY HISOBLASH
# ═══════════════════════════════════════════════════════════

async def recalculate_popularity(
    session: AsyncSession,
    anime_id: int,
) -> float:
    """
    Popularity score = (views_7d × 0.4) + (rating × 0.4) + (admin_pop × 0.2)
    Normalize qilinadi 0–100 ga.
    """
    from datetime import datetime, timedelta
    week_ago = datetime.utcnow() - timedelta(days=7)

    # 7 kunlik views
    cnt_result = await session.execute(
        select(func.count(ViewRecord.id))
        .where(
            ViewRecord.anime_id == anime_id,
            ViewRecord.viewed_at >= week_ago
        )
    )
    views_7d = cnt_result.scalar() or 0

    anime = await session.get(Anime, anime_id)
    if not anime:
        return 0.0

    # Score
    views_norm = min(views_7d / 500.0, 1.0)    # 500+ view = max
    rating_norm = anime.rating / 10.0
    admin_pop_norm = min((anime.popularity or 0) / 10.0, 1.0)

    score = (views_norm * 0.4 + rating_norm * 0.4 + admin_pop_norm * 0.2) * 100
    anime.popularity_score = round(score, 2)

    # Hidden gem tekshirish
    anime.is_hidden_gem = (anime.rating >= 8.0 and views_7d <= 100)

    await session.commit()
    return anime.popularity_score


async def record_view(
    session: AsyncSession,
    anime_id: int,
    user_id: int | None = None,
) -> None:
    """Har bir kontent ko'rishni yozadi va views counter oshiradi."""
    record = ViewRecord(anime_id=anime_id, user_id=user_id)
    session.add(record)

    anime = await session.get(Anime, anime_id)
    if anime:
        anime.views = (anime.views or 0) + 1

    await session.commit()

    # Har 10 ta viewda popularity qayta hisoblash
    if anime and anime.views % 10 == 0:
        await recalculate_popularity(session, anime_id)


async def add_to_watch_history(
    session: AsyncSession,
    user_id: int,
    anime_id: int,
    episode: int = 1,
    is_completed: bool = False,
) -> None:
    """
    User watch historyga qo'shadi (max 5 ta, eski o'chadi).
    Smart Continue va Recommendation uchun ishlatiladi.
    """
    # Mavjudmi?
    existing = await session.execute(
        select(UserWatchHistory).where(
            UserWatchHistory.user_id  == user_id,
            UserWatchHistory.anime_id == anime_id,
        )
    )
    hw = existing.scalar_one_or_none()

    if hw:
        hw.last_episode  = max(hw.last_episode, episode)
        hw.is_completed  = is_completed
        hw.watched_at    = func.now()
    else:
        # Max 5 ta qoidasi
        count_result = await session.execute(
            select(func.count(UserWatchHistory.id))
            .where(UserWatchHistory.user_id == user_id)
        )
        count = count_result.scalar() or 0

        if count >= 5:
            # Eng eskisini o'chirish
            oldest = await session.execute(
                select(UserWatchHistory)
                .where(UserWatchHistory.user_id == user_id)
                .order_by(UserWatchHistory.watched_at.asc())
                .limit(1)
            )
            old = oldest.scalar_one_or_none()
            if old:
                await session.delete(old)

        new_hw = UserWatchHistory(
            user_id=user_id,
            anime_id=anime_id,
            last_episode=episode,
            is_completed=is_completed,
        )
        session.add(new_hw)

    await session.commit()

    # Taste profile yangilash
    anime = await session.get(Anime, anime_id)
    if anime:
        await update_taste_profile(session, user_id, anime)


# ═══════════════════════════════════════════════════════════
#  YORDAMCHI
# ═══════════════════════════════════════════════════════════

def _anime_to_dict(anime: Anime, score: float = 0.0, extra: dict = None) -> dict:
    d = {
        "id":           anime.id,
        "title":        anime.title,
        "type":         anime.content_type or "anime",
        "year":         anime.year,
        "genres":       anime.genres or [],
        "tags":         anime.tags   or [],
        "mood":         anime.mood   or [],
        "rating":       anime.rating,
        "episodes":     anime.episodes_count,
        "status":       anime.status,
        "description":  anime.description,
        "poster_file_id":        anime.poster_file_id,
        "inline_thumbnail_url":  anime.inline_thumbnail_url,
        "trailer_file_id":       anime.trailer_file_id,
        "popularity_score":      anime.popularity_score,
        "is_hidden_gem":         anime.is_hidden_gem,
        "is_pro_locked":         anime.is_pro_locked,
        "score":        score,
    }
    if extra:
        d.update(extra)
    return d