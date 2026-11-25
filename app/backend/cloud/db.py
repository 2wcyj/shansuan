"""Cloud PostgreSQL engine helpers, isolated from the local SQLCipher store."""
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_cloud_engine(database_url: str, **options) -> AsyncEngine:
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("Cloud database URL must use postgresql+asyncpg")
    return create_async_engine(database_url, pool_pre_ping=True, **options)
