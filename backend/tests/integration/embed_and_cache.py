import asyncio

from app.services.embeddings.factory import get_embedder
from app.services.semantic_cache.factory import get_semantic_cache
from app.services.semantic_cache.schemas import CacheMetadata


async def main() -> None:
    # 1. Sample data
    sample_query = "What are the requirements for MSEUF admission?"
    sample_response = "Applicants need Form 138, a certificate of good moral character, and a 2x2 photo."

    # 2. Embed the query
    embedder = get_embedder()
    embedding_res = embedder.embed_one(sample_query)
    vector = embedding_res.values

    # 3. Save to cache
    cache = get_semantic_cache()
    await cache.set(
        query=sample_query,
        vector=vector,
        response=sample_response,
        metadata=CacheMetadata(
            doc_ids=["doc-mseuf-admissions-001"],
            chunk_ids=["chunk-042"],
        ),
    )

    print("[SUCCESS] Cached entry successfully.")


if __name__ == "__main__":
    asyncio.run(main())