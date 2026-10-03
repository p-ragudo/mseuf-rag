import sys
from pathlib import Path
import uuid
import asyncio

# Ensure backend root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scraper.ingest import load_and_chunk_knowledge_base
from app.services.llm_qgen.schema import RawChunk, GeneratedQuestion
from app.services.llm_qgen.factory import get_question_generator

def extract_question_text(q) -> str:
    if isinstance(q, str):
        return q
    if hasattr(q, "content"):
        return q.content
    if hasattr(q, "question"):
        return q.question
    if hasattr(q, "text"):
        return q.text
    if isinstance(q, dict):
        return q.get("content") or q.get("question") or q.get("text") or str(q)
    return str(q)

async def run_test_pipeline(page_limit: int = 3):
    print(f"=== Starting Test Pipeline (Max Chunks Limit: {page_limit}) ===")
    
    # 1. Load and chunk (limit to first N items)
    all_chunks = load_and_chunk_knowledge_base()
    test_chunks = all_chunks[:page_limit]
    print(f"[+] Loaded {len(test_chunks)} test chunks.")

    # 2. Setup output destinations using Pao's schema
    raw_chunks_cp = JsonlCheckpoint(
        filepath=Path("data/test_raw_chunks.jsonl"), 
        key_field="id"
    )
    gen_questions_cp = JsonlCheckpoint(
        filepath=Path("data/test_generated_questions.jsonl"), 
        key_field="id"
    )

    generator = get_question_generator()

    # 3. Process each chunk
    for chunk in test_chunks:
        print(f"\nProcessing Chunk [{chunk.id}] - Title: {chunk.title}")
        
        # Save RawChunk
        raw_chunks_cp.record(chunk.model_dump())
        print(f"  -> Saved RawChunk: {chunk.id}")

        # Generate questions via LLM
        try:
            result = await generator.generate_questions(chunk)
            
            raw_list = []
            if isinstance(result, list):
                raw_list = result
            elif hasattr(result, "questions"):
                raw_list = result.questions
            elif isinstance(result, dict) and "questions" in result:
                raw_list = result["questions"]

            # Map into strict GeneratedQuestion schema
            created_questions = []
            for item in raw_list:
                q_text = extract_question_text(item)
                if q_text.strip():
                    gq = GeneratedQuestion(
                        id=f"gq_{uuid.uuid4().hex[:10]}",
                        chunk_id=chunk.id,
                        content=q_text,
                        tags=chunk.tags
                    )
                    gen_questions_cp.record(gq.model_dump())
                    created_questions.append(gq.content)

            print(f"  -> Saved {len(created_questions)} GeneratedQuestion records.")
            for q in created_questions:
                print(f"     * {q}")

        except Exception as e:
            print(f"  [!] Error generating questions for chunk {chunk.id}: {e}")

        # Polite delay to prevent rate limits
        await asyncio.sleep(4.5)

    print("\n=== Test Pipeline Complete ===")
    print(f"Outputs written to:")
    print(" - backend/data/test_raw_chunks.jsonl")
    print(" - backend/data/test_generated_questions.jsonl")

if __name__ == "__main__":
    asyncio.run(run_test_pipeline(page_limit=3))