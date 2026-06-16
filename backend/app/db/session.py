from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Base

settings = get_settings()
engine = create_async_engine(
    settings.postgres_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS ocr_pages INTEGER DEFAULT 0")
        )
        await conn.execute(
            text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0")
        )
        await conn.execute(
            text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS progress_message VARCHAR(256)"
            )
        )
        await conn.execute(
            text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS toc_entries JSONB")
        )
        await conn.execute(
            text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_type "
                "VARCHAR(128) DEFAULT 'application/pdf'"
            )
        )
        await conn.execute(
            text(
                """
                DO $$ BEGIN
                    ALTER TYPE documentstatus ADD VALUE 'deleting';
                EXCEPTION
                    WHEN duplicate_object THEN NULL;
                END $$;
                """
            )
        )
        await conn.execute(
            text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS embeds JSONB")
        )
        await conn.execute(
            text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS caption TEXT")
        )
        await conn.execute(
            text("ALTER TABLE chunk_assets ADD COLUMN IF NOT EXISTS caption TEXT")
        )
