import sys
from pathlib import Path

# Dynamic root anchor: 2 levels up to 'backend'
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import json
import asyncio
from typing import List, Optional, Set
from dotenv import load_dotenv

load_dotenv()

from app.services.ingestion.schema import RawChunk, GeneratedQuestion
from app.services.ingestion.llm_qgen.factory import get_question_generator
from app.services.ingestion.llm_qgen.base_qgen import BaseQuestionGenerator

MIN_WORDS_PER_CHUNK = 10


async def generate_questions_for_chunk(
    chunk: RawChunk,
    generator: BaseQuestionGenerator,
    semaphore: asyncio.Semaphore,
    max_retries: int = 3,
) -> Optional[List[GeneratedQuestion]]:
    if len(chunk.content.split()) < MIN_WORDS_PER_CHUNK:
        return []

    async with semaphore:
        for attempt in range(max_retries):
            try:
                questions = await generator.generate_questions(chunk)
                return questions
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"[Error] Failed chunk {chunk.chunk_id} after {max_retries} attempts: {e}")
                    return None
                await asyncio.sleep(2 ** attempt)
        return None


async def process_all_chunks(
    input_chunks: List[RawChunk],
    output_path: Path,
    provider: Optional[str] = None,
    concurrency_limit: int = 10,
):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generator = get_question_generator(provider)

    # 1. Resume checkpoints via foreign key lookup
    processed_chunk_ids: Set[str] = set()
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    if item.get("chunk_id"):
                        processed_chunk_ids.add(item["chunk_id"])

    unprocessed = [c for c in input_chunks if c.chunk_id not in processed_chunk_ids]
    print(f"Total: {len(input_chunks)} | Already Processed: {len(processed_chunk_ids)} | Remaining: {len(unprocessed)}")

    if not unprocessed:
        print("All chunks are already processed.")
        return

    # 2. Process concurrently
    semaphore = asyncio.Semaphore(concurrency_limit)
    tasks = [generate_questions_for_chunk(chunk, generator, semaphore) for chunk in unprocessed]

    # 3. Stream write normalized questions to JSONL
    completed_count = 0
    with open(output_path, "a", encoding="utf-8") as f:
        for future in asyncio.as_completed(tasks):
            questions = await future
            completed_count += 1
            if questions:
                for q in questions:
                    f.write(q.model_dump_json() + "\n")
                f.flush()
            
            if completed_count % 25 == 0 or completed_count == len(unprocessed):
                print(f"Progress: {completed_count}/{len(unprocessed)} chunks finished")


if __name__ == "__main__":
    # When not run as a script, for testing:
    sample_data = [
        RawChunk(
            chunk_id="chunk_001",
            document_id="doc_001",
            source_url="https://example.edu/registrar/shifting",
            title="College Shifting Procedures",
            content="Students applying for a shift of program must submit their approved Shifting Form to the Registrar by week 3 of the semester.",
            tags=["Registrar", "Academic Policy", "Undergraduate"]
        ),
        RawChunk(
            chunk_id="chunk_002",
            document_id="doc_002",
            source_url="https://example.edu/scholarships/guidelines",
            title="Academic Scholarship Guidelines",
            content="To maintain an academic scholarship, students must have a general weighted average of 1.75 or higher with no failing grades.",
            tags=["Scholarships", "Financial Aid", "Requirements"]
        )
    ]

    asyncio.run(
        process_all_chunks(
            input_chunks=sample_data,
            output_path=Path("data/generated_questions/questions.jsonl"),
            concurrency_limit=5
        )
    )