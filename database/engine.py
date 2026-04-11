import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

load_dotenv()
DB_URL = os.getenv("DB_URL")

Base = declarative_base()

engine = create_async_engine(
    DB_URL,
    echo=False,
    pool_size=20,
    max_overflow=30,
    pool_recycle=3600,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Barcha migration — mavjud bo'lsa o'tkazib yuboradi
MIGRATIONS = [
    # Animes — eski ustunlar
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS total_episodes INTEGER DEFAULT 0",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS inline_thumbnail_url VARCHAR(500)",
    # Animes — Pro ustunlar
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS content_type VARCHAR(20) DEFAULT 'anime'",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS mood JSONB DEFAULT '[]'",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS episodes_count INTEGER",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS duration INTEGER",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'ongoing'",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS popularity FLOAT DEFAULT 0.0",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS popularity_score FLOAT DEFAULT 0.0",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS is_hidden_gem BOOLEAN DEFAULT FALSE",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS is_pro_locked BOOLEAN DEFAULT FALSE",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS added_by_id BIGINT",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS added_by_username VARCHAR(100)",
    "ALTER TABLE animes ADD COLUMN IF NOT EXISTS added_at TIMESTAMP DEFAULT NOW()",
    # Users — Pro ustunlar
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_pro BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS pro_until TIMESTAMP",
    # Admins — qo'shimcha
    "ALTER TABLE admins ADD COLUMN IF NOT EXISTS added_by BIGINT",
    "ALTER TABLE admins ADD COLUMN IF NOT EXISTS added_at TIMESTAMP DEFAULT NOW()",
    # AnimeSubscription jadvali
    """
    CREATE TABLE IF NOT EXISTS anime_subscriptions (
        id         SERIAL PRIMARY KEY,
        anime_id   INTEGER NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
        user_id    BIGINT  NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE (anime_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_anisub_anime ON anime_subscriptions(anime_id)",
    "CREATE INDEX IF NOT EXISTS ix_anisub_user  ON anime_subscriptions(user_id)",
    # related_content jadvali
    """
    CREATE TABLE IF NOT EXISTS related_content (
        id            SERIAL PRIMARY KEY,
        anime_id      INTEGER NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
        related_id    INTEGER NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
        relation_type VARCHAR(20) DEFAULT 'similar'
    )
    """,
    # user_watch_history jadvali
    """
    CREATE TABLE IF NOT EXISTS user_watch_history (
        id           SERIAL PRIMARY KEY,
        user_id      BIGINT  NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
        anime_id     INTEGER NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
        watched_at   TIMESTAMP DEFAULT NOW(),
        last_episode INTEGER DEFAULT 1,
        is_completed BOOLEAN DEFAULT FALSE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_wh_user  ON user_watch_history(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_wh_anime ON user_watch_history(anime_id)",
    # view_records jadvali
    """
    CREATE TABLE IF NOT EXISTS view_records (
        id        SERIAL PRIMARY KEY,
        anime_id  INTEGER NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
        user_id   BIGINT,
        viewed_at TIMESTAMP DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_vr_anime ON view_records(anime_id)",
    # user_taste_profiles jadvali
    """
    CREATE TABLE IF NOT EXISTS user_taste_profiles (
        id              SERIAL PRIMARY KEY,
        user_id         BIGINT NOT NULL UNIQUE REFERENCES users(telegram_id) ON DELETE CASCADE,
        fav_genres      JSONB DEFAULT '{}',
        fav_tags        JSONB DEFAULT '{}',
        fav_moods       JSONB DEFAULT '{}',
        fav_type        VARCHAR(20),
        avg_rating_pref FLOAT DEFAULT 7.0,
        updated_at      TIMESTAMP DEFAULT NOW()
    )
    """,
]


async def init_db():
    try:
        # Avval modellarni import qilish (jadval yaratish uchun)
        from database.models import (
            User, Admin, Anime, Series, SubscriptionChannel,
            AnimeRating, AnimeSubscription, RelatedContent,
            UserWatchHistory, UserTasteProfile, ViewRecord
        )

        async with engine.begin() as conn:
            # SQLAlchemy modellari orqali asosiy jadvallarni yaratish
            await conn.run_sync(Base.metadata.create_all)

            # Qo'shimcha migration — xato bo'lsa o'tkazib yuboradi
            for migration in MIGRATIONS:
                migration = migration.strip()
                if not migration:
                    continue
                try:
                    await conn.execute(text(migration))
                except Exception as e:
                    err = str(e).lower()
                    # Allaqachon mavjud bo'lsa — normal holat
                    if any(x in err for x in ("already exists", "duplicate", "already")):
                        pass
                    else:
                        print(f"[MIGRATION WARNING] {str(e)[:80]}")

        print("--- [INFO] Baza jadvallari tayyor! ---")

    except Exception as e:
        print(f"--- [ERROR] Bazada xato: {e} ---")
        raise