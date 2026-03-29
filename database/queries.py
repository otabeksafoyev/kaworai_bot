from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User, SubscriptionChannel, Anime, AnimeRating, Series


# ===== USER =====

async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    username: str | None = None,
) -> tuple:
    user = await session.get(User, telegram_id)
    if user:
        return user, False
    user = User(telegram_id=telegram_id, full_name=full_name, username=username)
    session.add(user)
    await session.commit()
    return user, True


async def get_user_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(User.telegram_id)))
    return result.scalar()


# ===== CHANNELS =====

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
            SubscriptionChannel.is_news == True,
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
        channel_id=channel_id,
        username=username,
        channel_url=channel_url,
        channel_name=channel_name,
        is_active=True,
        require_check=require_check,
        is_news=is_news
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


# ===== ANIME =====

async def get_anime_by_id(session: AsyncSession, anime_id: int) -> Anime | None:
    return await session.get(Anime, anime_id)


async def get_all_animes(session: AsyncSession) -> list:
    result = await session.execute(select(Anime).order_by(Anime.id.desc()))
    return result.scalars().all()


# ===== RATING =====

async def get_user_rating(
    session: AsyncSession,
    anime_id: int,
    user_id: int
) -> AnimeRating | None:
    result = await session.execute(
        select(AnimeRating).where(
            AnimeRating.anime_id == anime_id,
            AnimeRating.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def add_or_update_rating(
    session: AsyncSession,
    anime_id: int,
    user_id: int,
    score: int
) -> float:
    existing = await get_user_rating(session, anime_id, user_id)
    if existing:
        existing.score = score
    else:
        new_rating = AnimeRating(anime_id=anime_id, user_id=user_id, score=score)
        session.add(new_rating)

    await session.commit()

    # O'rtacha reytingni hisoblash
    result = await session.execute(
        select(func.avg(AnimeRating.score)).where(AnimeRating.anime_id == anime_id)
    )
    avg = result.scalar() or 0.0

    count_result = await session.execute(
        select(func.count(AnimeRating.id)).where(AnimeRating.anime_id == anime_id)
    )
    count = count_result.scalar() or 0

    # Anime jadvalidagi reytingni yangilash
    anime = await session.get(Anime, anime_id)
    if anime:
        anime.rating = round(float(avg), 1)
        anime.rating_count = count
        await session.commit()

    return round(float(avg), 1)


async def has_watched_all(
    session: AsyncSession,
    anime_id: int,
    user_id: int
) -> bool:
    """Foydalanuvchi oxirgi qismgacha ko'rganmi?"""
    # Oxirgi qismni olish
    result = await session.execute(
        select(func.max(Series.episode)).where(Series.anime_id == anime_id)
    )
    last_ep = result.scalar()
    if not last_ep:
        return False

    # UserWatch jadvalini tekshirish (keyinroq qo'shamiz)
    # Hozircha oxirgi qismni ko'rish callback orqali tekshiramiz
    return True  # callbacks.py da to'g'ri tekshiriladi