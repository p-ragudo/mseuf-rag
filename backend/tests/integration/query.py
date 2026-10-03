import asyncio
from app.services.query_pipeline.query_pipeline import QueryPipeline
from app.services.query_pipeline.schema import PipelineQueryRequest

query = "when is admissions for sy 2026-2027"


def display_retrieved_chunks(contexts):
    if not contexts:
        print("  [No chunks retrieved]")
        return

    print(f"  Total Chunks Retrieved: {len(contexts)}")
    for idx, ctx in enumerate(contexts, start=1):
        preview = ctx.content.replace("\n", " ").strip()
        if len(preview) > 160:
            preview = preview[:160] + "..."
        print(f"\n  [{idx}] Title: {ctx.title}")
        print(f"      Source: {ctx.source_url}")
        print(f"      Branch/Entity: {ctx.campus.upper()} | Level: {ctx.academic_level.upper()}")
        print(f"      Length: {len(ctx.content)} chars")

        ce_score_str = f"{ctx.rerank_score:.4f}" if ctx.rerank_score is not None else "N/A"
        rrf_score_str = f"{ctx.initial_score:.4f}" if ctx.initial_score is not None else "N/A"
        print(f"      Cross-Encoder Score: {ce_score_str} | Upstream RRF Score: {rrf_score_str}")

        print("      Matched Question(s) & Similarity Scores:")
        if ctx.matched_questions:
            for q_info in ctx.matched_questions:
                print(
                    f"        • [{q_info.method.upper()}] (score: {q_info.score:.4f}, rank: {q_info.rank}) "
                    f"\"{q_info.question}\""
                )
        else:
            print("        [No synthetic questions logged]")
        print(f"      Text:   {preview}")


async def main():
    print("Initializing Staging Query Pipeline (Redis + Qdrant + Fast Embed + Gemini QA)...")
    pipeline = QueryPipeline()

    request_data = PipelineQueryRequest(
        query=query,
        org_id=1,
        top_k=5,
    )

    print("\n" + "=" * 80)
    print("--- TEST 1: Cold Execution (Expecting Multi-Vector RRF + Cross-Encoder Rerank) ---")
    print("=" * 80)
    res_1 = await pipeline.execute(request_data)
    print(f"Query:     {query}")
    print(f"Answer:\n{res_1.answer}\n")
    print(f"Source:    {res_1.source}")
    print(f"Is Cached: {res_1.is_cached}")
    print(f"Sources:   {res_1.sources}")
    print("\n--- Retrieved Chunks (Reranked Contexts with Scores) ---")
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
    print("\n--- Retrieved Chunks (From Redis Cache with Preserved Metrics) ---")
    display_retrieved_chunks(res_2.contexts)


if __name__ == "__main__":
    asyncio.run(main())