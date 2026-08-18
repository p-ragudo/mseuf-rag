import asyncio
import json
import os
from pathlib import Path
from typing import Any, List

from app.services.vector_db.schema import VectorPoint
from app.services.vector_db.factory import get_vector_db

from scripts.sample_data import SAMPLE_CHUNKS
from app.scraper.ingest import load_and_chunk_knowledge_base

use_test_db = (
    os.getenv("USE_TEST_QDRANT_DB", "false")
    .lower()
    in ("true", "1", "yes")
)

use_real_data = (
    os.getenv("SCRIPT_QGEN_USE_REAL_DATA", "false")
    .lower()
    in ("true", "1", "yes")
)

DENSE_COLLECTION_NAME = os.getenv("DENSE_COLLECTION_NAME", "questions_collection")
CHUNKS_COLLECTION_NAME = os.getenv("CHUNKS_COLLECTION_NAME", "chunks_collection")
VECTOR_DIM = 384

JSONL_FILE_PATH = ""
if use_real_data:
    JSONL_FILE_PATH = Path(__file__).resolve().parent.parent / "data" / "generated_questions" / "questions.jsonl"
else:
    JSONL_FILE_PATH = Path(__file__).resolve().parent.parent / "data" / "generated_questions" / "test_questions.jsonl"

def normalize_tags(raw_tags: Any) -> List[str]:
    """Ensures tags are strictly a flat list of clean strings."""
    if not raw_tags:
        return []
    if isinstance(raw_tags, str):
        return [t.strip() for t in raw_tags.split(",") if t.strip()]
    if isinstance(raw_tags, list):
        flattened: List[str] = []
        for item in raw_tags:
            if isinstance(item, list):
                flattened.extend(str(sub).strip() for sub in item if str(sub).strip())
            elif item is not None and str(item).strip():
                flattened.append(str(item).strip())
        return flattened
    return [str(raw_tags).strip()]


def load_jsonl_points(file_path: Path) -> List[VectorPoint]:
    points: List[VectorPoint] = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f):
            clean_line = line.strip()
            if not clean_line:
                continue

            record = json.loads(clean_line)
            point_id = str(record.get("id", line_num))
            question_text = record.get("question") or record.get("content")

            if not question_text:
                continue

            payload = {
                "chunk_id": record.get("chunk_id"),
                "question": question_text,
                "tags": normalize_tags(record.get("tags")),
                "source": record.get("source", None),
            }

            # vector=None lets Qdrant Cloud Inference handle embedding via Document
            points.append(VectorPoint(id=point_id, vector=None, payload=payload))

    return points


async def main() -> None:
    if not JSONL_FILE_PATH.exists():
        raise FileNotFoundError(f"Input file not found at: {JSONL_FILE_PATH}")

    points = load_jsonl_points(JSONL_FILE_PATH)

    print(f"Loaded {len(points)} points from {JSONL_FILE_PATH}")

    if not points:
        print("No valid points found to insert.")
        return

    # Provider automatically resolves endpoint and key based on environment settings
    db = get_vector_db()

    try:
        await db.create_collection_if_not_exists(collection_name=DENSE_COLLECTION_NAME, vector_size=VECTOR_DIM)
        await db.create_collection_if_not_exists(collection_name=CHUNKS_COLLECTION_NAME)

        current_db_mode = ""
        chunks = []
        if use_test_db:
            current_db_mode = "TEST DATABASE"
            chunks = SAMPLE_CHUNKS
        else:
            current_db_mode = "PRODUCTION DATABASE"
            chunks = load_and_chunk_knowledge_base()

        print(f"Saving {len(points)} points to '{DENSE_COLLECTION_NAME}' in {current_db_mode}")
        await db.upsert_points(collection_name=DENSE_COLLECTION_NAME, points=points)
        print("Successfully saved all question vectors.")

        print(f"Saving {len(chunks)} chunks to {CHUNKS_COLLECTION_NAME} in {current_db_mode}")
        await db.upsert_payload_only(
            collection_name=CHUNKS_COLLECTION_NAME, 
            records=[chunk.model_dump() for chunk in SAMPLE_CHUNKS]
        )
        print("Successfully saved all chunks.")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())