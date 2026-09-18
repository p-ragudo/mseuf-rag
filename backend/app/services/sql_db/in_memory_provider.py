from typing import Dict, List, Optional, Tuple
from app.services.sql_db.base import DatabaseRepository
from app.services.sql_db.schema import ChunkStatus, DocumentChunk, ScrapedPage, ScrapedPageStatus

class InMemoryDatabaseRepository(DatabaseRepository):
    def __init__(self):
        self._pages_by_url: Dict[Tuple[str, str], ScrapedPage] = {}
        self._pages_by_id: Dict[str, ScrapedPage] = {}
        self._chunks: Dict[str, DocumentChunk] = {}

    async def upsert_page(self, page: ScrapedPage) -> ScrapedPage:
        key = (page.tenant_id, page.source_url)
        self._pages_by_url[key] = page
        self._pages_by_id[page.id] = page
        return page

    async def list_pages_by_status(
        self, tenant_id: str, status: ScrapedPageStatus, limit: int = 100
    ) -> List[ScrapedPage]:
        matches = [
            p for p in self._pages_by_id.values()
            if p.tenant_id == tenant_id and p.status == status
        ]
        return matches[:limit]

    async def update_page_status(self, page_id: str, status: ScrapedPageStatus) -> None:
        if page_id in self._pages_by_id:
            self._pages_by_id[page_id].status = status

    async def delete_chunks_for_page(self, scraped_page_id: str) -> None:
        self._chunks = {
            cid: c for cid, c in self._chunks.items()
            if c.scraped_page_id != scraped_page_id
        }

    async def save_chunks(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        for chunk in chunks:
            self._chunks[chunk.id] = chunk
        return chunks

    async def list_pending_chunks(self, tenant_id: str, limit: int = 100) -> List[DocumentChunk]:
        matches = [
            c for c in self._chunks.values()
            if c.tenant_id == tenant_id and c.status == ChunkStatus.PENDING_QGEN
        ]
        return matches[:limit]