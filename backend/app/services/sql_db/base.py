from abc import ABC, abstractmethod
from typing import List, Optional
from app.services.sql_db.schema import DocumentChunk, ScrapedPage, ScrapedPageStatus

class DatabaseRepository(ABC):
    """Abstract interface for scraped pages and chunk persistence."""

    # Page Operations
    @abstractmethod
    async def upsert_page(self, page: ScrapedPage) -> ScrapedPage:
        pass

    @abstractmethod
    async def list_pages_by_status(
        self, tenant_id: str, status: ScrapedPageStatus, limit: int = 100
    ) -> List[ScrapedPage]:
        pass

    @abstractmethod
    async def update_page_status(self, page_id: str, status: ScrapedPageStatus) -> None:
        pass

    # Chunk Operations
    @abstractmethod
    async def save_chunks(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        pass

    @abstractmethod
    async def delete_chunks_for_page(self, scraped_page_id: str) -> None:
        """Deletes existing chunks for a page before re-inserting new ones."""
        pass

    @abstractmethod
    async def list_pending_chunks(self, tenant_id: str, limit: int = 100) -> List[DocumentChunk]:
        """Fetches chunks ready for LLM question generation."""
        pass