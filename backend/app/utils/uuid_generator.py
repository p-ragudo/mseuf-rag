import uuid
from typing import Optional

KB_NAMESPACE: uuid.UUID = uuid.UUID("a3bb189e-8bf9-4888-9912-ace4e6543002")


def generate_uuid(*, seed: str) -> str:
    """Generates a deterministic UUIDv5 within the KB namespace."""
    return str(uuid.uuid5(KB_NAMESPACE, seed))

def generate_doc_id(
    *,
    source_url: str,
) -> str:
    """Generates a deterministic document-level ID based on source URL."""
    seed = f"doc::{source_url.strip()}"
    return generate_uuid(seed=seed)


def generate_chunk_id(
    *,
    source_url: str,
    chunk_index: int,
    content: str,
) -> str:
    """Combines document origin, sequential index, and text to prevent collisions."""
    seed = f"chunk::{source_url}#{chunk_index}:{content.strip()}"
    return generate_uuid(seed=seed)


def generate_question_id(
    *,
    chunk_id: str,
    question: str,
) -> str:
    """Generates a deterministic ID bound to the parent chunk and question text."""
    seed = f"question::{chunk_id}:{question.strip()}"
    return generate_uuid(seed=seed)


def generate_sparse_id(
    *,
    parent_id: str,
    model_name: Optional[str] = "bm25",
) -> str:
    """Generates a deterministic ID for a sparse representation tied to its source entity."""
    seed = f"sparse::{model_name}:{parent_id}"
    return generate_uuid(seed=seed)