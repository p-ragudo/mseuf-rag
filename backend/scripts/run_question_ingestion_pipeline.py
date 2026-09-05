import sys
from pathlib import Path

# Dynamic root anchor: 2 levels up to 'backend'
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import asyncio
from typing import List
from dotenv import load_dotenv

load_dotenv()

from app.services.ingestion.schema import RawChunk

# Import runners directly from your existing scripts
from scripts.run_qgen import process_all_chunks
from scripts.run_save_to_db import main as run_save_to_db_main
from scripts.sample_data import SAMPLE_CHUNKS

# Path configuration
DEFAULT_JSONL_PATH = BACKEND_ROOT / "data" / "generated_questions" / "questions.jsonl"


async def run_pipeline(chunks: List[RawChunk], output_path: Path = DEFAULT_JSONL_PATH):
    print("--- [1/2] Generating Synthetic Questions ---")
    await process_all_chunks(
        input_chunks=chunks,
        output_path=output_path,
        concurrency_limit=5,
    )

    print("\n--- [2/2] Ingesting Questions into Vector DB ---")
    await run_save_to_db_main()
    print("\nPipeline execution complete.")


if __name__ == "__main__":
    asyncio.run(run_pipeline(chunks=SAMPLE_CHUNKS))