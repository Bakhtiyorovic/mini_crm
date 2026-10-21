from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from models.models import Base
import os
from dotenv import load_dotenv

DB_URL = "sqlite+aiosqlite:///hostel_db.sqlite3"

load_dotenv()

print(f"DEBUG DB URL: '{DB_URL}'")
engine = create_async_engine(DB_URL, echo=False)

# SQLite uchun asinxron engine (echo=False bo'lsa konsolga SQL yozuvlari chiqmaydi)
engine = create_async_engine(DB_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)