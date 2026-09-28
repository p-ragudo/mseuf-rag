import asyncio
from app.services.query_pipeline.query_pipeline import QueryPipeline
from app.services.query_pipeline.schema import PipelineQueryRequest

query = "When is the next admissions?"

async def main():
    print("Initializing Staging Query Pipeline (Redis + Qdrant + Embedder + Gemini QA)...")
    pipeline = QueryPipeline()

    # Pass the org_id corresponding to your indexed dataset
    request_data = PipelineQueryRequest(
        query=query,
        org_id=1,
        top_k=10,
    )

    print("\n--- TEST 1: Cold Execution (Expecting Cache Miss -> Qdrant Hybrid Search -> Gemini QA) ---")
    res_1 = await pipeline.execute(request_data)
    print(f"Query: {query}")
    print(f"Answer:\n{res_1.answer}\n")
    print(f"Source:     {res_1.source}")
    print(f"Is Cached:  {res_1.is_cached}")
    print(f"Sources:    {res_1.sources}")

    print("\n--- TEST 2: Warm Execution (Expecting Redis Semantic Cache Hit) ---")
    res_2 = await pipeline.execute(request_data)
    print(f"Query: {query}")
    print(f"Answer:\n{res_2.answer}\n")
    print(f"Source:     {res_2.source}")
    print(f"Is Cached:  {res_2.is_cached}")
    print(f"Sources:    {res_2.sources}")


if __name__ == "__main__":
    asyncio.run(main())