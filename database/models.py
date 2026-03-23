from sqlalchemy import Column, Integer, BigInteger, String, Text, JSON, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
# DIQQAT: engine.py ichidagi Base-ni import qilamiz
from database.engine import Base 

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=True)
    joined_at = Column(DateTime, server_default=func.now())

class Anime(Base):
    __tablename__ = "animes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    poster_file_id = Column(String(300), nullable=True)
    genres = Column(JSON, nullable=True)
    year = Column(Integer, nullable=True)
    rating = Column(Float, default=0.0)
    views = Column(Integer, default=0)
    
    # Seriyalar bilan bog'lanish (Statistika uchun qulay)
    episodes = relationship("Series", back_populates="anime", cascade="all, delete-orphan")

class Series(Base):
    __tablename__ = "series"
    id = Column(Integer, primary_key=True, autoincrement=True)
    anime_id = Column(Integer, ForeignKey("animes.id", ondelete="CASCADE"))
    episode = Column(Integer, nullable=False)
    file_id = Column(String(300), nullable=False)
    
    anime = relationship("Anime", back_populates="episodes")

class Admin(Base):
    __tablename__ = "admins"
    telegram_id = Column(BigInteger, primary_key=True)
    nickname = Column(String(100), nullable=True)
    role = Column(String(20), default="admin")  # owner / partner

class SubscriptionChannel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)