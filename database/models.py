from sqlalchemy import Column, Integer, BigInteger, String, Text, JSON, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database.engine import Base


# ═══════════════════════════════════════════════════════════
#  MAVJUD MODELLAR (o'zgartirilgan + kengaytirilgan)
# ═══════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    username    = Column(String(100), nullable=True)
    full_name   = Column(String(200), nullable=True)
    joined_at   = Column(DateTime, server_default=func.now())

    # ✅ Pro maydonlari
    is_pro    = Column(Boolean, default=False)
    pro_until = Column(DateTime, nullable=True)

    # ✅ Pro relationships
    watch_history = relationship("UserWatchHistory", back_populates="user", cascade="all, delete-orphan")
    taste_profile = relationship("UserTasteProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Anime(Base):
    __tablename__ = "animes"
    id                   = Column(Integer, primary_key=True, autoincrement=False)
    title                = Column(String(255), nullable=False)
    description          = Column(Text, nullable=True)
    poster_file_id       = Column(String(300), nullable=True)
    trailer_file_id      = Column(String(300), nullable=True)
    inline_thumbnail_url = Column(String(500), nullable=True)
    genres               = Column(JSON, nullable=True)
    year                 = Column(Integer, nullable=True)
    rating               = Column(Float, default=0.0)
    rating_count         = Column(Integer, default=0)
    total_episodes       = Column(Integer, default=0)
    views                = Column(Integer, default=0)

    # ✅ Pro maydonlari
    content_type     = Column(String(20), default="anime")       # anime | movie | serial | dorama
    tags             = Column(JSON, default=list)
    mood             = Column(JSON, default=list)
    episodes_count   = Column(Integer, nullable=True)
    duration         = Column(Integer, nullable=True)            # daqiqada
    status           = Column(String(20), default="ongoing")     # ongoing | completed | announced
    popularity       = Column(Float, default=0.0)
    popularity_score = Column(Float, default=0.0)
    is_hidden_gem    = Column(Boolean, default=False)
    is_pro_locked    = Column(Boolean, default=False)

    # Mavjud relationships
    episodes = relationship("Series", back_populates="anime", cascade="all, delete-orphan")
    ratings  = relationship("AnimeRating", back_populates="anime", cascade="all, delete-orphan")

    # ✅ Pro relationships
    related_to    = relationship("RelatedContent", foreign_keys="RelatedContent.anime_id",
                                 back_populates="anime", cascade="all, delete-orphan")
    watch_records = relationship("UserWatchHistory", back_populates="anime", cascade="all, delete-orphan")
    view_records  = relationship("ViewRecord", back_populates="anime", cascade="all, delete-orphan")


class Series(Base):
    __tablename__ = "series"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    anime_id = Column(Integer, ForeignKey("animes.id", ondelete="CASCADE"))
    episode  = Column(Integer, nullable=False)
    file_id  = Column(String(300), nullable=False)
    anime    = relationship("Anime", back_populates="episodes")


class AnimeRating(Base):
    __tablename__ = "anime_ratings"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    anime_id = Column(Integer, ForeignKey("animes.id", ondelete="CASCADE"))
    user_id  = Column(BigInteger, nullable=False)
    score    = Column(Integer, nullable=False)
    anime    = relationship("Anime", back_populates="ratings")


class Admin(Base):
    __tablename__ = "admins"
    telegram_id = Column(BigInteger, primary_key=True)
    nickname    = Column(String(100), nullable=True)
    role        = Column(String(20), default="admin")


class SubscriptionChannel(Base):
    __tablename__ = "channels"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    channel_id   = Column(BigInteger, unique=True, nullable=True)
    username     = Column(String(100), nullable=True)
    channel_url  = Column(String(256), nullable=False)
    channel_name = Column(String(128), nullable=False)
    is_active    = Column(Boolean, default=True)
    require_check = Column(Boolean, default=False)
    is_news      = Column(Boolean, default=False)


# ═══════════════════════════════════════════════════════════
#  YANGI PRO MODELLAR
# ═══════════════════════════════════════════════════════════

class RelatedContent(Base):
    """Anime lar orasidagi bog'liqlik (sequel, prequel, spin-off...)"""
    __tablename__ = "related_content"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    anime_id      = Column(Integer, ForeignKey("animes.id", ondelete="CASCADE"), nullable=False)
    related_id    = Column(Integer, ForeignKey("animes.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String(20), default="similar")  # sequel | prequel | spin-off | similar

    anime         = relationship("Anime", foreign_keys=[anime_id], back_populates="related_to")
    related_anime = relationship("Anime", foreign_keys=[related_id])


class UserWatchHistory(Base):
    """Foydalanuvchi tomosha tarixi"""
    __tablename__ = "user_watch_history"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    anime_id     = Column(Integer, ForeignKey("animes.id", ondelete="CASCADE"), nullable=False)
    watched_at   = Column(DateTime, default=func.now())
    last_episode = Column(Integer, default=1)
    is_completed = Column(Boolean, default=False)

    user  = relationship("User", back_populates="watch_history")
    anime = relationship("Anime", back_populates="watch_records")


class UserTasteProfile(Base):
    """Foydalanuvchining did profili (AI tavsiya uchun)"""
    __tablename__ = "user_taste_profiles"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
                             nullable=False, unique=True)
    fav_genres      = Column(JSON, default=dict)   # {"action": 5, "drama": 3}
    fav_tags        = Column(JSON, default=dict)
    fav_moods       = Column(JSON, default=dict)
    fav_type        = Column(String(20), nullable=True)
    avg_rating_pref = Column(Float, default=7.0)
    updated_at      = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="taste_profile")


class ViewRecord(Base):
    """Ko'rishlar tarixi (trending va popularity uchun)"""
    __tablename__ = "view_records"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    anime_id  = Column(Integer, ForeignKey("animes.id", ondelete="CASCADE"), nullable=False)
    user_id   = Column(BigInteger, nullable=True)
    viewed_at = Column(DateTime, default=func.now())

    anime = relationship("Anime", back_populates="view_records")