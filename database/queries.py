from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import (
    User, SubscriptionChannel, Anime, AnimeRating,
    Series, AnimeSubscription
)
from datetime import datetime


# ═══════════════════════════════════════════════════════════
#  USER
# ═══════════════════════════════════════════════════════════

async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    username: str | None = None,
) -> tuple:
    user = await session.get(User, telegram_id)
    if user:
        if username and user.username != username:
            user.username = username
            await session.commit()
        return user, False
    user = User(telegram_id=telegram_id, full_name=full_name, username=username)
    session.add(user)
    await session.commit()
    return user, True


async def get_user_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(User.telegram_id)))
    return result.scalar()


# ═══════════════════════════════════════════════════════════
#  CHANNELS
# ═══════════════════════════════════════════════════════════

async def get_active_channels(session: AsyncSession) -> list:
    result = await session.execute(
        select(SubscriptionChannel).where(SubscriptionChannel.is_active == True)
    )
    return result.scalars().all()


async def get_all_channels(session: AsyncSession) -> list:
    result = await session.execute(select(SubscriptionChannel))
    return result.scalars().all()


async def get_news_channels(session: AsyncSession) -> list:
    result = await session.execute(
        select(SubscriptionChannel).where(
            SubscriptionChannel.is_news   == True,
            SubscriptionChannel.is_active == True
        )
    )
    return result.scalars().all()


async def add_channel(
    session: AsyncSession,
    channel_name: str,
    channel_url: str,
    require_check: bool = False,
    is_news: bool = False,
    channel_id: int | None = None,
    username: str | None = None,
) -> SubscriptionChannel:
    ch = SubscriptionChannel(
        channel_id=channel_id, username=username,
        channel_url=channel_url, channel_name=channel_name,
        is_active=True, require_check=require_check, is_news=is_news
    )
    session.add(ch)
    await session.commit()
    await session.refresh(ch)
    return ch


async def remove_channel(session: AsyncSession, ch_id: int) -> bool:
    result = await session.execute(
        delete(SubscriptionChannel).where(SubscriptionChannel.id == ch_id)
    )
    await session.commit()
    return result.rowcount > 0


async def toggle_channel(session: AsyncSession, ch_id: int) -> bool | None:
    result = await session.execute(
        select(SubscriptionChannel).where(SubscriptionChannel.id == ch_id)
    )
    ch = result.scalar_one_or_none()
    if not ch:
        return None
    ch.is_active = not ch.is_active
    await session.commit()
    return ch.is_active


# ═══════════════════════════════════════════════════════════
#  ANIME
# ═══════════════════════════════════════════════════════════

async def get_anime_by_id(session: AsyncSession, anime_id: int) -> Anime | None:
    return await session.get(Anime, anime_id)


async def get_all_animes(session: AsyncSession) -> list:
    result = await session.execute(select(Anime).order_by(Anime.id.desc()))
    return result.scalars().all()


# ═══════════════════════════════════════════════════════════
#  RATING
# ═══════════════════════════════════════════════════════════

async def get_user_rating(
    session: AsyncSession, anime_id: int, user_id: int
) -> AnimeRating | None:
    result = await session.execute(
        select(AnimeRating).where(
            AnimeRating.anime_id == anime_id,
            AnimeRating.user_id  == user_id
        )
    )
    return result.scalar_one_or_none()


async def add_or_update_rating(
    session: AsyncSession, anime_id: int, user_id: int, score: int
) -> float:
    existing = await get_user_rating(session, anime_id, user_id)
    if existing:
        existing.score = score
    else:
        session.add(AnimeRating(anime_id=anime_id, user_id=user_id, score=score))
    await session.commit()

    avg = (await session.execute(
        select(func.avg(AnimeRating.score)).where(AnimeRating.anime_id == anime_id)
    )).scalar() or 0.0

    count = (await session.execute(
        select(func.count(AnimeRating.id)).where(AnimeRating.anime_id == anime_id)
    )).scalar() or 0

    anime = await session.get(Anime, anime_id)
    if anime:
        anime.rating       = round(float(avg), 1)
        anime.rating_count = count
        await session.commit()

    return round(float(avg), 1)


# ═══════════════════════════════════════════════════════════
#  PRO USER
# ═══════════════════════════════════════════════════════════

async def is_pro_user(session: AsyncSession, user_id: int) -> bool:
    user = await session.get(User, user_id)
    if not user or not user.is_pro:
        return False
    if user.pro_until and user.pro_until < datetime.utcnow():
        user.is_pro    = False
        user.pro_until = None
        await session.commit()
        return False
    return True


# ═══════════════════════════════════════════════════════════
#  ANIME OBUNA
# ═══════════════════════════════════════════════════════════

async def subscribe_anime(
    session: AsyncSession, anime_id: int, user_id: int
) -> None:
    existing = await session.execute(
        select(AnimeSubscription).where(
            AnimeSubscription.anime_id == anime_id,
            AnimeSubscription.user_id  == user_id
        )
    )
    if existing.scalar_one_or_none():
        return
    session.add(AnimeSubscription(anime_id=anime_id, user_id=user_id))
    await session.commit()


async def unsubscribe_anime(
    session: AsyncSession, anime_id: int, user_id: int
) -> None:
    await session.execute(
        delete(AnimeSubscription).where(
            AnimeSubscription.anime_id == anime_id,
            AnimeSubscription.user_id  == user_id
        )
    )
    await session.commit()


async def is_subscribed_anime(
    session: AsyncSession, anime_id: int, user_id: int
) -> bool:
    result = await session.execute(
        select(AnimeSubscription).where(
            AnimeSubscription.anime_id == anime_id,
            AnimeSubscription.user_id  == user_id
        )
    )
    return result.scalar_one_or_none() is not None


async def get_anime_subscribers(
    session: AsyncSession, anime_id: int
) -> list[int]:
    result = await session.execute(
        select(AnimeSubscription.user_id).where(
            AnimeSubscription.anime_id == anime_id
        )
    )
    return [r[0] for r in result.fetchall()]


# ═══════════════════════════════════════════════════════════
#  WATCH HISTORY — LIMIT YO'Q, TO'G'RI is_completed
# ═══════════════════════════════════════════════════════════

async def add_to_watch_history(
    session: AsyncSession,
    user_id: int,
    anime_id: int,
    episode: int = 1,
    is_completed: bool = False,
) -> None:
    """
    Watch historyga yozadi.
    MUHIM o'zgarishlar:
      - Limit YO'Q (eski 5 ta limit olib tashlandi)
      - is_completed: haqiqiy oxirgi qismga yetganda True
      - Taste profile ham yangilanadi
    """
    try:
        from database.models import UserWatchHistory
        result = await session.execute(
            select(UserWatchHistory).where(
                UserWatchHistory.user_id  == user_id,
                UserWatchHistory.anime_id == anime_id,
            )
        )
        hw = result.scalar_one_or_none()

        if hw:
            # Faqat yuqori episode saqlanadi
            if episode > hw.last_episode:
                hw.last_episode = episode
            # is_completed faqat True ga o'tadi, False ga qaytmaydi
            if is_completed:
                hw.is_completed = True
            hw.watched_at = func.now()
        else:
            session.add(UserWatchHistory(
                user_id=user_id,
                anime_id=anime_id,
                last_episode=episode,
                is_completed=is_completed,
            ))

        await session.commit()

        # Taste profile yangilash
        anime = await session.get(Anime, anime_id)
        if anime:
            try:
                from utils.recommendation import update_taste_profile
                await update_taste_profile(session, user_id, anime)
            except Exception:
                pass

    except Exception:
        pass


async def record_view(
    session: AsyncSession,
    anime_id: int,
    user_id: int | None = None,
) -> None:
    """Ko'rishni yozadi va views counter oshiradi."""
    try:
        from database.models import ViewRecord
        session.add(ViewRecord(anime_id=anime_id, user_id=user_id))
        anime = await session.get(Anime, anime_id)
        if anime:
            anime.views = (anime.views or 0) + 1
        await session.commit()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  ADMIN: ANIME TO'LIQ MA'LUMOT
# ═══════════════════════════════════════════════════════════

async def get_anime_full_info(
    session: AsyncSession, anime_id: int
) -> dict | None:
    anime = await session.get(Anime, anime_id)
    if not anime:
        return None

    ep_count = (await session.execute(
        select(func.count(Series.id)).where(Series.anime_id == anime_id)
    )).scalar() or 0

    sub_count = (await session.execute(
        select(func.count(AnimeSubscription.user_id))
        .where(AnimeSubscription.anime_id == anime_id)
    )).scalar() or 0

    try:
        pro_sub_count = (await session.execute(
            select(func.count(AnimeSubscription.user_id))
            .join(User, AnimeSubscription.user_id == User.telegram_id)
            .where(
                AnimeSubscription.anime_id == anime_id,
                User.is_pro == True
            )
        )).scalar() or 0
    except Exception:
        pro_sub_count = 0

    return {
        "id":                anime.id,
        "title":             anime.title,
        "type":              getattr(anime, "content_type", None) or "anime",
        "year":              anime.year,
        "genres":            anime.genres or [],
        "tags":              getattr(anime, "tags",  None) or [],
        "mood":              getattr(anime, "mood",  None) or [],
        "rating":            anime.rating or 0.0,
        "rating_count":      anime.rating_count or 0,
        "episodes_count":    ep_count,
        "status":            getattr(anime, "status", None) or "ongoing",
        "is_pro_locked":     getattr(anime, "is_pro_locked", False),
        "is_hidden_gem":     getattr(anime, "is_hidden_gem", False),
        "views":             anime.views or 0,
        "subscribers":       sub_count,
        "pro_subscribers":   pro_sub_count,
        "added_by_id":       getattr(anime, "added_by_id",       None),
        "added_by_username": getattr(anime, "added_by_username", None),
        "added_at":          getattr(anime, "added_at",          None),
        "description":       anime.description,
    }