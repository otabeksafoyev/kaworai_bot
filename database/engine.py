import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# .env faylini yuklaymiz
load_dotenv()
DB_URL = os.getenv("DB_URL")

# Base ob'ekti - bu hamma modellarni "ro'yxatga oluvchi" markaz
# Uni modellarda ishlatish uchun export qilamiz
Base = declarative_base()

# Engine yaratish (200k user uchun optimallashgan)
engine = create_async_engine(
    DB_URL, 
    echo=False,  # Dastur tayyor bo'lgach False qiling, aks holda loglar juda ko'payib ketadi
    pool_size=20,           # Bir vaqtning o'zida ochiq turadigan ulanishlar soni
    max_overflow=10,        # Zarurat tug'ilganda qo'shimcha ochiladigan ulanishlar
    pool_recycle=3600,      # Har soatda ulanishlarni yangilab turish
)

# Session yaratuvchi (Factory)
AsyncSessionLocal = sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

async def init_db():
    """Jadvallarni bazada yaratish funksiyasi"""
    # MUHIM: Bu yerda hamma modellarni import qilish shart!
    # Aks holda Base.metadata jadvallar borligini bilmaydi.
    try:
        from database.models import User, Admin, Anime, Series, SubscriptionChannel
        
        async with engine.begin() as conn:
            # Jadvallarni yaratish buyrug'i
            await conn.run_sync(Base.metadata.create_all)
            print("--- [INFO] Ma'lumotlar bazasi jadvallari muvaffaqiyatli yaratildi! ---")
    except Exception as e:
        print(f"--- [ERROR] Bazani yaratishda xato: {e} ---")