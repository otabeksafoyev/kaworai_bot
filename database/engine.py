import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

load_dotenv()
DB_URL = os.getenv("DB_URL")

Base = declarative_base()

engine = create_async_engine(
    DB_URL,
    echo=False,
    pool_size=20,
    max_overflow=30,
    pool_recycle=3600,
    pool_pre_ping=True,  # Ulanish uzilsa avtomatik qayta ulash
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def init_db():
    try:
        from database.models import User, Admin, Anime, Series, SubscriptionChannel
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            print("--- [INFO] Baza jadvallari tayyor! ---")
    except Exception as e:
        print(f"--- [ERROR] Bazada xato: {e} ---")