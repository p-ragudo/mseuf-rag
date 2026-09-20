from typing import List, Optional
import asyncpg

from app.services.sql_db.base import DatabaseRepository
from app.services.sql_db.schema import (
    ChunkStatus,
    DocumentChunk,
    ScrapedPage,
    ScrapedPageStatus,
)


def _get_val(enum_or_str) -> str:
    """Safely extracts raw string from either a string or an Enum instance."""
    return enum_or_str.value if hasattr(enum_or_str, "value") else str(enum_or_str)


class PostgresDatabaseRepository(DatabaseRepository):
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Initializes connection pool and ensures schema exists."""
        if not self._pool:
            clean_dsn = str(self._dsn).replace("postgresql+asyncpg://", "postgresql://")

            self._pool = await asyncpg.create_pool(
                dsn=clean_dsn,
                min_size=2,
                max_size=10,
            )
            await self._run_migrations()

    async def close(self):
        if self._pool:
            await self._pool.close()

    async def _run_migrations(self):
        query = """
        CREATE TABLE IF NOT EXISTS scraped_pages (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            source_url TEXT NOT NULL,
            raw_markdown TEXT NOT NULL,
            content_hash CHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'SCRAPED',
            scraped_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_scraped_pages_tenant_url UNIQUE (tenant_id, source_url)
        );

        CREATE INDEX IF NOT EXISTS idx_scraped_pages_tenant_status 
        ON scraped_pages (tenant_id, status);

        CREATE TABLE IF NOT EXISTS document_chunks (
            id VARCHAR(36) PRIMARY KEY,
            scraped_page_id VARCHAR(36) NOT NULL REFERENCES scraped_pages(id) ON DELETE CASCADE,
            tenant_id VARCHAR(64) NOT NULL,
            source_url TEXT NOT NULL,
            title VARCHAR(255) NOT NULL,
            chunk_index INT NOT NULL,
            content TEXT NOT NULL,
            content_hash CHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'PENDING_QGEN',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_document_chunks_page_index UNIQUE (scraped_page_id, chunk_index)
        );

        CREATE INDEX IF NOT EXISTS idx_document_chunks_tenant_status 
        ON document_chunks (tenant_id, status);
        """
        async with self._pool.acquire() as conn:
            await conn.execute(query)

    async def upsert_page(self, page: ScrapedPage) -> ScrapedPage:
        query = """
        INSERT INTO scraped_pages (
            id, tenant_id, source_url, raw_markdown, content_hash, status, scraped_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (tenant_id, source_url) DO UPDATE SET
            raw_markdown = EXCLUDED.raw_markdown,
            content_hash = EXCLUDED.content_hash,
            status = CASE 
                WHEN scraped_pages.content_hash != EXCLUDED.content_hash THEN 'SCRAPED'
                ELSE scraped_pages.status
            END,
            scraped_at = EXCLUDED.scraped_at
        RETURNING id, tenant_id, source_url, raw_markdown, content_hash, status, scraped_at;
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                page.id,
                page.tenant_id,
                page.source_url,
                page.raw_markdown,
                page.content_hash,
                _get_val(page.status),
                page.scraped_at,
            )
            return ScrapedPage(**dict(row))

    async def list_pages_by_status(
        self, tenant_id: str, status: ScrapedPageStatus, limit: int = 100
    ) -> List[ScrapedPage]:
        query = """
        SELECT id, tenant_id, source_url, raw_markdown, content_hash, status, scraped_at
        FROM scraped_pages
        WHERE tenant_id = $1 AND status = $2
        ORDER BY scraped_at ASC
        LIMIT $3;
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, _get_val(status), limit)
            return [ScrapedPage(**dict(row)) for row in rows]

    async def update_page_status(self, page_id: str, status: ScrapedPageStatus) -> None:
        query = "UPDATE scraped_pages SET status = $1 WHERE id = $2;"
        async with self._pool.acquire() as conn:
            await conn.execute(query, _get_val(status), page_id)

    async def delete_chunks_for_page(self, scraped_page_id: str) -> None:
        query = "DELETE FROM document_chunks WHERE scraped_page_id = $1;"
        async with self._pool.acquire() as conn:
            await conn.execute(query, scraped_page_id)

    async def save_chunks(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        if not chunks:
            return []

        query = """
        INSERT INTO document_chunks (
            id, scraped_page_id, tenant_id, source_url, title, chunk_index, content, content_hash, status, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            content_hash = EXCLUDED.content_hash,
            status = EXCLUDED.status;
        """
        data = [
            (
                c.id,
                c.scraped_page_id,
                c.tenant_id,
                c.source_url,
                c.title,
                c.chunk_index,
                c.content,
                c.content_hash,
                _get_val(c.status),
                c.created_at,
            )
            for c in chunks
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(query, data)
        return chunks

    async def list_pending_chunks(self, tenant_id: str, limit: int = 100) -> List[DocumentChunk]:
        query = """
        SELECT id, scraped_page_id, tenant_id, source_url, title, chunk_index, content, content_hash, status, created_at
        FROM document_chunks
        WHERE tenant_id = $1 AND status = $2
        ORDER BY chunk_index ASC
        LIMIT $3;
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, _get_val(ChunkStatus.PENDING_QGEN), limit)
            return [DocumentChunk(**dict(row)) for row in rows]