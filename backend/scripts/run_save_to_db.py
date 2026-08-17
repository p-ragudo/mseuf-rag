import asyncio
import json
from pathlib import Path
from typing import Any, List

from app.services.vector_db.qdrant_provider_cloud_inference import QdrantCloudInferenceProvider
from app.services.vector_db.schema import VectorPoint
from app.services.vector_db.vdb_service import VectorDatabaseService

COLLECTION_NAME = "questions_collection"
VECTOR_DIM = 384
EMBEDDING_MODEL = "sentence-transformers/all-minilm-l6-v2"
JSONL_FILE_PATH = Path(__file__).resolve().parent.parent / "data" / "generated_questions" / "questions.jsonl"


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

    sample_points = load_jsonl_points(JSONL_FILE_PATH)
    print(f"Loaded {len(sample_points)} points from {JSONL_FILE_PATH}")

    if not sample_points:
        print("No valid points found to insert.")
        return

    # Provider automatically resolves endpoint and key based on environment settings
    provider = QdrantCloudInferenceProvider(default_model=EMBEDDING_MODEL)
    vdb_service = VectorDatabaseService(db=provider)

    try:
        await vdb_service.ensure_collection(
            collection_name=COLLECTION_NAME,
            vector_dim=VECTOR_DIM,
        )

        print(f"Saving {len(sample_points)} points to '{COLLECTION_NAME}' via VectorDatabaseService...")
        await vdb_service.save_question_vectors(
            collection_name=COLLECTION_NAME,
            points=sample_points,
        )
        print("Successfully saved all question vectors.")
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())