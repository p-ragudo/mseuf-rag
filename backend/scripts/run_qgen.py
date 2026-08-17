import json
import asyncio
from pathlib import Path
from typing import List
from app.services.ingestion.llm_qgen.qgen import RawChunk, EnrichedChunk
from app.services.ingestion.llm_qgen.factory import get_question_generator
from app.services.ingestion.llm_qgen.base import BaseQuestionGenerator

async def generate_questions_for_chunk(
    chunk: RawChunk,
    generator: BaseQuestionGenerator,
    semaphore: asyncio.Semaphore,
    max_retries: int = 3,
) -> EnrichedChunk:
    async with semaphore:
        for attempt in range(max_retries):
            try:
                result = await generator.generate_questions(chunk)
                return EnrichedChunk(
                    **chunk.model_dump(),
                    generated_questions=result.questions
                )
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"[Error] Failed chunk {chunk.chunk_id}: {e}\n[ERROR] Traceback: run_qgen.py:generate_questions_for_chunk")
                    return EnrichedChunk(**chunk.model_dump(), generated_questions=[])
                await asyncio.sleep(2 ** attempt)

async def process_all_chunks(
    input_chunks: List[RawChunk],
    output_path: Path,
    provider: str = None,
    concurrency_limit: int = 10,
):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generator = get_question_generator(provider)

    processed_ids = set()
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    processed_ids.add(item["chunk_id"])

    unprocessed = [c for c in input_chunks if c.chunk_id not in processed_ids]
    print(f"Total: {len(input_chunks)} | Processed: {len(processed_ids)} | Remaining: {len(unprocessed)}")

    semaphore = asyncio.Semaphore(concurrency_limit)
    tasks = [generate_questions_for_chunk(chunk, generator, semaphore) for chunk in unprocessed]

    with open(output_path, "a", encoding="utf-8") as f:
        for future in asyncio.as_completed(tasks):
            enriched = await future
            f.write(enriched.model_dump_json() + "\n")
            f.flush()

if __name__ == "__main__":
    # Test batch using Pydantic instances
    sample_data = [
        RawChunk(
            chunk_id="chunk_001",
            document_id="doc_001",  # Added required field
            source_url="https://example.edu/registrar/shifting",
            title="College Shifting Procedures",
            content="Students applying for a shift of program must submit their approved Shifting Form to the Registrar by week 3 of the semester."
        ),
        RawChunk(
            chunk_id="chunk_002",
            document_id="doc_002",  # Added required field
            source_url="https://example.edu/scholarships/guidelines",
            title="Academic Scholarship Guidelines",
            content="To maintain an academic scholarship, students must have a general weighted average of 1.75 or higher with no failing grades."
        )
    ]

    asyncio.run(
        process_all_chunks(
            input_chunks=sample_data,
            output_path=Path("data/generated_questions/enriched_chunks.jsonl"),
            concurrency_limit=5
        )
    )