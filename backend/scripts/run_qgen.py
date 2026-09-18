import sys
from pathlib import Path

# Add backend root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from typing import Any, List, Optional, Union

from app.scraper.ingest import load_and_chunk_knowledge_base
from backend.app.services.llm_qgen.base_qgen import BaseQuestionGenerator
from backend.app.services.llm_qgen.factory import get_question_generator
from backend.app.services.llm_qgen.schema import RawChunk
from app.utils.checkpoint import JsonlCheckpoint


class EnrichedChunk(RawChunk):
    generated_questions: List[Any] = []


def extract_question_text(q: Any) -> str:
    """Extract string text from a GeneratedQuestion object, dict, or raw string."""
    if isinstance(q, str):
        return q
    if hasattr(q, "question"):
        return q.question
    if hasattr(q, "text"):
        return q.text
    if isinstance(q, dict):
        return q.get("question") or q.get("text") or str(q)
    return str(q)


async def generate_with_backoff(
    chunk: RawChunk,
    generator: BaseQuestionGenerator,
    max_retries: int = 5,
) -> Optional[EnrichedChunk]:
    for attempt in range(max_retries):
        try:
            result = await generator.generate_questions(chunk)
            
            # Extract raw questions list from response
            if isinstance(result, list):
                raw_list = result
            elif hasattr(result, "questions"):
                raw_list = result.questions
            elif isinstance(result, dict) and "questions" in result:
                raw_list = result["questions"]
            else:
                raw_list = []

            # Extract string texts from objects
            questions = [extract_question_text(q) for q in raw_list if q]

            if not questions:
                raise ValueError(f"No valid questions extracted from result: {result}")

            return EnrichedChunk(
                **chunk.model_dump(),
                generated_questions=questions,
            )
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                wait_sec = 25 * (attempt + 1)
                print(f"[Rate Limit] Chunk {chunk.id}: Hit 429 quota. Waiting {wait_sec}s...")
                await asyncio.sleep(wait_sec)
            else:
                wait_sec = 2**attempt
                print(f"[Retry {attempt + 1}/{max_retries}] Chunk {chunk.id}: {e}. Waiting {wait_sec}s...")
                await asyncio.sleep(wait_sec)

    print(f"[Error] Skipping chunk {chunk.id} after {max_retries} failed attempts.")
    return None


async def process_all_chunks(
    input_chunks: List[RawChunk],
    checkpoint_path: Path,
    provider: str = None,
    delay_between_requests: float = 4.5,
):
    checkpoint = JsonlCheckpoint(filepath=checkpoint_path, key_field="id")
    generator = get_question_generator(provider)

    unprocessed = [c for c in input_chunks if not checkpoint.is_completed(c.id)]
    print(
        f"Total Chunks: {len(input_chunks)} | "
        f"Already Processed: {checkpoint.completed_count} | "
        f"Remaining: {len(unprocessed)}"
    )

    if not unprocessed:
        print("[✔] All chunks are already generated and up to date.")
        return

    for chunk in unprocessed:
        enriched = await generate_with_backoff(chunk, generator)
        if enriched:
            checkpoint.record(enriched.model_dump())
            print(f"[+] Saved chunk {enriched.id} ({len(enriched.generated_questions)} questions)")

        # Pacing delay to guarantee staying under 15 requests per minute
        await asyncio.sleep(delay_between_requests)


if __name__ == "__main__":
    chunks = load_and_chunk_knowledge_base()

    asyncio.run(
        process_all_chunks(
            input_chunks=chunks,
            checkpoint_path=Path("data/generated_questions/enriched_chunks.jsonl"),
            delay_between_requests=4.5,
        )
    )