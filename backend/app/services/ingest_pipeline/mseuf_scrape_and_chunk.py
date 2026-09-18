import asyncio
from app.services.sql_db.postgres_provider import PostgresDatabaseRepository
from app.services.ingest_pipeline.scrape import scrape_site
from app.services.ingest_pipeline.chunk import process_and_chunk_pages
from app.core.config import settings

DATABASE_URL = settings.database_url


async def main():
    repo = PostgresDatabaseRepository(dsn=DATABASE_URL)
    await repo.connect()

    try:
        tenant = "mseuf"

        # 1. Scrape (streamed, writes to Postgres after each page finishes)
        await scrape_site(
            start_url="https://mseuf.edu.ph",
            tenant_id=tenant,
            repo=repo,
            max_depth=1,
        )

        # 2. Chunk (splits and writes chunks to Postgres immediately per page)
        chunks = await process_and_chunk_pages(tenant_id=tenant, repo=repo)
        print(f"Generated {len(chunks)} chunks ready for QGen.")

    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())