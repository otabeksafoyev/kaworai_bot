"""
Kaworai Pro — Database Migration
Mavjud PostgreSQL bazaga yangi ustunlar va jadvallar qo'shadi.

FOYDALANISH:
  python migration.py

Bu script mavjud ma'lumotlarni o'CHMAYDI.
Faqat yangi ustunlar va jadvallar qo'shadi.
"""

import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DB_URL", os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/kaworai"))



MIGRATION_SQL = """
-- ════════════════════════════════════════════════
-- 1. USERS jadvaliga Pro maydonlari
-- ════════════════════════════════════════════════
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_pro      BOOLEAN  DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pro_until   TIMESTAMP NULL;


-- ════════════════════════════════════════════════
-- 2. ANIMES jadvaliga yangi Pro maydonlar
-- ════════════════════════════════════════════════
ALTER TABLE animes
    ADD COLUMN IF NOT EXISTS content_type    VARCHAR(20)  DEFAULT 'anime',
    ADD COLUMN IF NOT EXISTS tags            JSONB        DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS mood            JSONB        DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS episodes_count  INTEGER      NULL,
    ADD COLUMN IF NOT EXISTS duration        INTEGER      NULL,
    ADD COLUMN IF NOT EXISTS status          VARCHAR(20)  DEFAULT 'ongoing',
    ADD COLUMN IF NOT EXISTS popularity      FLOAT        DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS popularity_score FLOAT       DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS is_hidden_gem   BOOLEAN      DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_pro_locked   BOOLEAN      DEFAULT FALSE;

-- Mavjud genres ustunini JSONB ga o'tkazish (agar TEXT bo'lsa)
-- (SQLAlchemy JSON → PostgreSQL JSONB ishlaydi, skip)


-- ════════════════════════════════════════════════
-- 3. RELATED_CONTENT jadval
-- ════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS related_content (
    id            SERIAL PRIMARY KEY,
    anime_id      INTEGER NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
    related_id    INTEGER NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
    relation_type VARCHAR(20) DEFAULT 'similar'
);

CREATE INDEX IF NOT EXISTS ix_related_anime_id ON related_content(anime_id);


-- ════════════════════════════════════════════════
-- 4. USER_WATCH_HISTORY jadval
-- ════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS user_watch_history (
    id           SERIAL PRIMARY KEY,
    user_id      BIGINT    NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    anime_id     INTEGER   NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
    watched_at   TIMESTAMP DEFAULT NOW(),
    last_episode INTEGER   DEFAULT 1,
    is_completed BOOLEAN   DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS ix_watch_history_user       ON user_watch_history(user_id);
CREATE INDEX IF NOT EXISTS ix_watch_history_user_anime ON user_watch_history(user_id, anime_id);


-- ════════════════════════════════════════════════
-- 5. USER_TASTE_PROFILES jadval
-- ════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS user_taste_profiles (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT UNIQUE NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    fav_genres      JSONB   DEFAULT '{}',
    fav_tags        JSONB   DEFAULT '{}',
    fav_moods       JSONB   DEFAULT '{}',
    fav_type        VARCHAR(20) NULL,
    avg_rating_pref FLOAT   DEFAULT 7.0,
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_taste_profile_user ON user_taste_profiles(user_id);


-- ════════════════════════════════════════════════
-- 6. VIEW_RECORDS jadval (popularity uchun)
-- ════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS view_records (
    id        SERIAL PRIMARY KEY,
    anime_id  INTEGER  NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
    user_id   BIGINT   NULL,
    viewed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_view_anime_id  ON view_records(anime_id);
CREATE INDEX IF NOT EXISTS ix_view_viewed_at ON view_records(viewed_at);


-- ════════════════════════════════════════════════
-- 7. PERFORMANCE indexes (animes)
-- ════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS ix_anime_type       ON animes(content_type);
CREATE INDEX IF NOT EXISTS ix_anime_rating     ON animes(rating);
CREATE INDEX IF NOT EXISTS ix_anime_popularity ON animes(popularity_score);
CREATE INDEX IF NOT EXISTS ix_anime_year       ON animes(year);
"""


async def run_migration():
    print("🔄 Migration boshlandi...")
    # asyncpg uchun URL formatini moslashtirish
    db_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    db_url = db_url.replace("postgresql://", "")

    conn = await asyncpg.connect(dsn=f"postgresql://{db_url}" if not DATABASE_URL.startswith("postgresql://") else DATABASE_URL)

    try:
        statements = [s.strip() for s in MIGRATION_SQL.split(";") if s.strip()]
        for stmt in statements:
            if not stmt:
                continue
            try:
                await conn.execute(stmt)
                # Qisqa ko'rsatish
                first_line = stmt.split("\n")[0].strip()
                if first_line.startswith("--"):
                    print(f"  📌 {first_line[3:]}")
                else:
                    print(f"  ✅ {first_line[:60]}...")
            except Exception as e:
                if "already exists" in str(e) or "duplicate" in str(e).lower():
                    pass   # OK — allaqachon bor
                else:
                    print(f"  ⚠️ {str(e)[:100]}")

        print("\n✅ Migration muvaffaqiyatli tugadi!")
        print("\n📋 Yangi jadvallar/ustunlar:")
        print("  • users.is_pro, users.pro_until")
        print("  • animes.content_type, tags, mood, episodes_count, ...")
        print("  • related_content (yangi jadval)")
        print("  • user_watch_history (yangi jadval)")
        print("  • user_taste_profiles (yangi jadval)")
        print("  • view_records (yangi jadval)")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migration())