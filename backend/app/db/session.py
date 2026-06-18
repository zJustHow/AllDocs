from collections.abc import AsyncGenerator

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
        await conn.run_sync(_ensure_chunk_asset_columns)


def _ensure_chunk_asset_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    if "chunk_assets" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("chunk_assets")}
    if "figure_number" not in columns:
        sync_conn.execute(
            text("ALTER TABLE chunk_assets ADD COLUMN figure_number VARCHAR(32)")
        )
    if "figure_caption" not in columns:
        sync_conn.execute(
            text("ALTER TABLE chunk_assets ADD COLUMN figure_caption TEXT")
        )
