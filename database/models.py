from sqlalchemy import Column, Integer, BigInteger, String, Text, JSON, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database.engine import Base


class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=True)
    joined_at = Column(DateTime, server_default=func.now())


class Anime(Base):
    __tablename__ = "animes"
    id = Column(Integer, primary_key=True, autoincrement=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    poster_file_id = Column(String(300), nullable=True)
    trailer_file_id = Column(String(300), nullable=True)
    inline_thumbnail_url = Column(String(500), nullable=True)  # inline uchun URL
    genres = Column(JSON, nullable=True)
    year = Column(Integer, nullable=True)
    rating = Column(Float, default=0.0)
    rating_count = Column(Integer, default=0)   # nechta odam baho bergan
    views = Column(Integer, default=0)
    episodes = relationship("Series", back_populates="anime", cascade="all, delete-orphan")
    ratings = relationship("AnimeRating", back_populates="anime", cascade="all, delete-orphan")


class Series(Base):
    __tablename__ = "series"
    id = Column(Integer, primary_key=True, autoincrement=True)
    anime_id = Column(Integer, ForeignKey("animes.id", ondelete="CASCADE"))
    episode = Column(Integer, nullable=False)
    file_id = Column(String(300), nullable=False)
    anime = relationship("Anime", back_populates="episodes")


class AnimeRating(Base):
    __tablename__ = "anime_ratings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    anime_id = Column(Integer, ForeignKey("animes.id", ondelete="CASCADE"))
    user_id = Column(BigInteger, nullable=False)
    score = Column(Integer, nullable=False)  # 1-10
    anime = relationship("Anime", back_populates="ratings")


class Admin(Base):
    __tablename__ = "admins"
    telegram_id = Column(BigInteger, primary_key=True)
    nickname = Column(String(100), nullable=True)
    role = Column(String(20), default="admin")


class SubscriptionChannel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, unique=True, nullable=True)
    username = Column(String(100), nullable=True)
    channel_url = Column(String(256), nullable=False)
    channel_name = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True)
    require_check = Column(Boolean, default=False)
    is_news = Column(Boolean, default=False)   # news kanal belgisi