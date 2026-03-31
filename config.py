"""
Yangilangan config.py
Mavjud config.py ga quyidagi yangi o'zgaruvchilarni QO'SHING.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_ID:  int
    DB_URL:    str = "postgresql+asyncpg://user:pass@localhost/animebot"
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Mavjud ──
    SECRET_CHANNEL_ID: int = 0
    NEWS_CHANNEL_ID:   int = 0

    # ── YANGI: Pro to'lov tizimi ──
    PAYMENT_CHANNEL_ID: int    = -1003525618102   # Chek yuboradigan kanal
    CARD_NUMBER:        str    = "5614 6829 1317 5461"
    CARD_OWNER:         str    = "Saidova Yulduz"
    ADMIN_USERNAME:     str    = "safoyev9225"

    class Config:
        env_file          = ".env"
        env_file_encoding = "utf-8"


config = Settings()