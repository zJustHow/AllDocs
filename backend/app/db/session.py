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
        await conn.run_sync(_ensure_sessions_user_id)
        await conn.run_sync(_ensure_otp_challenge_columns)
        await conn.run_sync(_ensure_documents_chat_enabled)
        await conn.run_sync(_ensure_indexes)

    async with async_session_factory() as db:
        from app.services.auth_service import ensure_bootstrap_admin

        await ensure_bootstrap_admin(db)
        await db.commit()


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
    if "vlm_caption" not in columns:
        sync_conn.execute(text("ALTER TABLE chunk_assets ADD COLUMN vlm_caption TEXT"))
    if "content_hash" not in columns:
        sync_conn.execute(
            text("ALTER TABLE chunk_assets ADD COLUMN content_hash VARCHAR(64)")
        )
    if "layout_regions" not in columns:
        sync_conn.execute(text("ALTER TABLE chunk_assets ADD COLUMN layout_regions JSONB"))
    if "chunks" in inspector.get_table_names():
        chunk_columns = {column["name"] for column in inspector.get_columns("chunks")}
        if "sub_index" not in chunk_columns:
            if "step_index" in chunk_columns:
                sync_conn.execute(
                    text("ALTER TABLE chunks RENAME COLUMN step_index TO sub_index")
                )
            else:
                sync_conn.execute(text("ALTER TABLE chunks ADD COLUMN sub_index JSONB"))
        if "layout_regions" not in chunk_columns:
            sync_conn.execute(text("ALTER TABLE chunks ADD COLUMN layout_regions JSONB"))


def _ensure_otp_challenge_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    if "otp_challenges" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("otp_challenges")}
    if "email" not in columns:
        sync_conn.execute(text("ALTER TABLE otp_challenges ADD COLUMN email VARCHAR(256)"))
    if sync_conn.dialect.name == "postgresql" and "phone" in columns:
        sync_conn.execute(text("ALTER TABLE otp_challenges ALTER COLUMN phone DROP NOT NULL"))


def _ensure_sessions_user_id(sync_conn) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    if "sessions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("sessions")}
    if "user_id" not in columns:
        sync_conn.execute(text("ALTER TABLE sessions ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE SET NULL"))


def _ensure_documents_chat_enabled(sync_conn) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    if "documents" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "chat_enabled" not in columns:
        sync_conn.execute(
            text("ALTER TABLE documents ADD COLUMN chat_enabled BOOLEAN NOT NULL DEFAULT TRUE")
        )


def _ensure_indexes(sync_conn) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    table_names = set(inspector.get_table_names())
    index_statements = [
        (
            "chunks",
            "ix_chunks_document_id_chunk_index",
            "CREATE INDEX IF NOT EXISTS ix_chunks_document_id_chunk_index "
            "ON chunks (document_id, chunk_index)",
        ),
        (
            "chunks",
            "ix_chunks_document_id_page",
            "CREATE INDEX IF NOT EXISTS ix_chunks_document_id_page "
            "ON chunks (document_id, page)",
        ),
        (
            "chunk_assets",
            "ix_chunk_assets_chunk_id",
            "CREATE INDEX IF NOT EXISTS ix_chunk_assets_chunk_id "
            "ON chunk_assets (chunk_id)",
        ),
        (
            "chunk_assets",
            "ix_chunk_assets_document_id_figure_number",
            "CREATE INDEX IF NOT EXISTS ix_chunk_assets_document_id_figure_number "
            "ON chunk_assets (document_id, figure_number)",
        ),
        (
            "sessions",
            "ix_sessions_doc_ids",
            "CREATE INDEX IF NOT EXISTS ix_sessions_doc_ids "
            "ON sessions USING gin (doc_ids)",
        ),
        (
            "sessions",
            "ix_sessions_user_id",
            "CREATE INDEX IF NOT EXISTS ix_sessions_user_id "
            "ON sessions (user_id)",
        ),
        (
            "messages",
            "ix_messages_session_id_created_at",
            "CREATE INDEX IF NOT EXISTS ix_messages_session_id_created_at "
            "ON messages (session_id, created_at)",
        ),
        (
            "documents",
            "ix_documents_status_chat_enabled",
            "CREATE INDEX IF NOT EXISTS ix_documents_status_chat_enabled "
            "ON documents (status, chat_enabled)",
        ),
        (
            "refresh_tokens",
            "ix_refresh_tokens_token_hash",
            "CREATE INDEX IF NOT EXISTS ix_refresh_tokens_token_hash "
            "ON refresh_tokens (token_hash)",
        ),
    ]
    for table_name, index_name, ddl in index_statements:
        if table_name not in table_names:
            continue
        existing = {index["name"] for index in inspector.get_indexes(table_name)}
        if index_name not in existing:
            sync_conn.execute(text(ddl))
