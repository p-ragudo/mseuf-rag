import asyncio

from app.core.config import settings
from app.services.cache.factory import semantic_cache
from app.services.cache.schemas import CacheMetadata

def print_debug(message: str): print(f"[DEBUG] {message}")


async def main():
    print_debug(f"EMBEDDING MODEL: {settings.embedding_model}")
    print_debug(f"EMBEDDING PROVIDER: {settings.embedding_provider}")

    print_debug(f"SEMANTIC_CACHE_PROVIDER: {settings.semantic_cache_provider}")
    print_debug(f"SEMANTIC_CACHE_THRESHOLD: {settings.semantic_cache_threshold}")

    print("--- 1. Store Test ---")
    question = "How do I shift to another program?"
    answer = "Submit the Shifting Form to the Registrar by Week 3."

    await semantic_cache.set(
        query=question,
        response=answer,
        metadata=CacheMetadata(
            doc_ids=["doc_registrar_01"],
            chunk_ids=["chunk_shifting_01"],
        ),
    )
    print("✓ Stored in Redis!\n")

    await asyncio.sleep(3)

    print("--- 2. Similar Question Test ---")
    similar_question = "How is procedure for shifting?"
    hit = await semantic_cache.get(similar_question)
    if hit:
        print(f"✓ CACHE HIT! Matched Answer: {hit.response}\n")
    else:
        print("✗ CACHE MISS\n")

    print("--- 3. Unrelated Question Test ---")
    unrelated_question = "Where is the campus cafeteria?"
    unrelated_hit = await semantic_cache.get(unrelated_question)
    if unrelated_hit is None:
        print("✓ CACHE MISS (Expected)! Unrelated query bypassed successfully.\n")
    else:
        print(f"✗ UNEXPECTED HIT: {unrelated_hit.response}\n")


    if hasattr(semantic_cache, "_cache") and hasattr(semantic_cache._cache, "_redis"):
        await semantic_cache._cache._redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())