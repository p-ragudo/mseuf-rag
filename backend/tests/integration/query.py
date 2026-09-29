import asyncio
from app.services.query_pipeline.query_pipeline import QueryPipeline
from app.services.query_pipeline.schema import PipelineQueryRequest

query = "Programs offered for tech related courses?"


def display_retrieved_chunks(contexts):
    if not contexts:
        print("  [No chunks retrieved]")
        return

    print(f"  Total Chunks Retrieved: {len(contexts)}")
    for idx, ctx in enumerate(contexts, start=1):
        preview = ctx.content.replace("\n", " ").strip()
        if len(preview) > 180:
            preview = preview[:180] + "..."
        print(f"\n  [{idx}] Title: {ctx.title}")
        print(f"      Source: {ctx.source_url}")
        print(f"      Length: {len(ctx.content)} chars")
        print(f"      Text:   {preview}")


async def main():
    print("Initializing Staging Query Pipeline (Redis + Qdrant + Embedder + Gemini QA)...")
    pipeline = QueryPipeline()

    request_data = PipelineQueryRequest(
        query=query,
        org_id=1,
        top_k=10,
    )

    print("\n" + "=" * 80)
    print("--- TEST 1: Cold Execution (Expecting Cache Miss -> Qdrant Hybrid Search -> Gemini QA) ---")
    print("=" * 80)
    res_1 = await pipeline.execute(request_data)
    print(f"Query:     {query}")
    print(f"Answer:\n{res_1.answer}\n")
    print(f"Source:    {res_1.source}")
    print(f"Is Cached: {res_1.is_cached}")
    print(f"Sources:   {res_1.sources}")
    print("\n--- Retrieved Chunks (Grounding Context) ---")
    display_retrieved_chunks(res_1.contexts)

    print("\n" + "=" * 80)
    print("--- TEST 2: Warm Execution (Expecting Redis Semantic Cache Hit) ---")
    print("=" * 80)
    res_2 = await pipeline.execute(request_data)
    print(f"Query:     {query}")
    print(f"Answer:\n{res_2.answer}\n")
    print(f"Source:    {res_2.source}")
    print(f"Is Cached: {res_2.is_cached}")
    print(f"Sources:   {res_2.sources}")
    print("\n--- Retrieved Chunks (From Cache Extra Metadata) ---")
    display_retrieved_chunks(res_2.contexts)


if __name__ == "__main__":
    asyncio.run(main())