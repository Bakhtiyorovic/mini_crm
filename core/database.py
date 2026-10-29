from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from models.models import Base


load_dotenv()

DB_URL = "sqlite+aiosqlite:///hostel_db.sqlite3"

engine = create_async_engine(DB_URL, echo=False)

async_session = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]
                for column in inspect(sync_conn).get_columns("beds")
            }
        )

        if "guest_phone" not in columns:
            await conn.execute(
                text("ALTER TABLE beds ADD COLUMN guest_phone VARCHAR")
            )