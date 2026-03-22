from sqlalchemy import Column, Integer, BigInteger, String, Text, JSON, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String(100))
    full_name = Column(String(200))
    joined_at = Column(DateTime, server_default=func.now())

class Anime(Base):
    __tablename__ = "animes"
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    poster_file_id = Column(String(300))
    genres = Column(JSON)
    year = Column(Integer)
    rating = Column(Float, default=0.0)
    views = Column(Integer, default=0)

class Series(Base):
    __tablename__ = "series"
    id = Column(Integer, primary_key=True)
    anime_id = Column(Integer, ForeignKey("animes.id"))
    episode = Column(Integer)
    file_id = Column(String(300))

class Admin(Base):
    __tablename__ = "admins"
    telegram_id = Column(BigInteger, primary_key=True)
    nickname = Column(String(100))
    role = Column(String(20))  # owner / partner

class SubscriptionChannel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True)
    channel_id = Column(BigInteger, unique=True)
    username = Column(String(100))
    is_active = Column(Boolean, default=True)