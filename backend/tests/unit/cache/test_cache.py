import asyncio
from dotenv import load_dotenv

load_dotenv()

from app.services.cache.factory import semantic_cache
from app.services.cache.schemas import CacheMetadata


async def main():
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

    await asyncio.sleep(1)

    print("--- 2. Similar Question Test ---")
    similar_question = "What is the procedure for shifting to a different course?"
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


if __name__ == "__main__":
    asyncio.run(main())