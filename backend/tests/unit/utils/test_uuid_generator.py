import uuid
import pytest

from app.utils.uuid_generator import (
    generate_chunk_id,
    generate_doc_id,
    generate_question_id,
    generate_sparse_id,
    generate_uuid,
)


def is_valid_uuid(val: str) -> bool:
    """Helper to verify if a string is a valid UUIDv5."""
    try:
        parsed = uuid.UUID(val, version=5)
        return str(parsed) == val
    except (ValueError, AttributeError):
        return False


class TestUUIDGeneratorsDeterminism:
    def test_generate_uuid_determinism(self):
        seed = "test-seed-string"
        id_1 = generate_uuid(seed=seed)
        id_2 = generate_uuid(seed=seed)

        assert id_1 == id_2
        assert is_valid_uuid(id_1)

    def test_generate_doc_id_determinism_and_stripping(self):
        url = "https://example.edu/registrar/policy"
        
        id_1 = generate_doc_id(source_url=url)
        id_2 = generate_doc_id(source_url=url)
        # Leading/trailing whitespace should produce the exact same ID
        id_with_spaces = generate_doc_id(source_url=f"  {url}  ")

        assert id_1 == id_2
        assert id_1 == id_with_spaces
        assert is_valid_uuid(id_1)

    def test_generate_chunk_id_determinism_and_stripping(self):
        params = {
            "source_url": "https://example.edu/scholarships",
            "chunk_index": 0,
            "content": "Students must maintain a GWA of 1.75.",
        }

        id_1 = generate_chunk_id(**params)
        id_2 = generate_chunk_id(**params)
        id_with_spaces = generate_chunk_id(
            source_url=params["source_url"],
            chunk_index=params["chunk_index"],
            content=f"  {params['content']} \n\t ",
        )

        assert id_1 == id_2
        assert id_1 == id_with_spaces
        assert is_valid_uuid(id_1)

    def test_generate_question_id_determinism_and_stripping(self):
        chunk_id = generate_chunk_id(
            source_url="https://example.edu/scholarships",
            chunk_index=0,
            content="GWA requirements",
        )
        question_text = "What is the minimum GWA for a scholarship?"

        id_1 = generate_question_id(chunk_id=chunk_id, question=question_text)
        id_2 = generate_question_id(chunk_id=chunk_id, question=question_text)
        id_with_spaces = generate_question_id(
            chunk_id=chunk_id,
            question=f" {question_text} \n",
        )

        assert id_1 == id_2
        assert id_1 == id_with_spaces
        assert is_valid_uuid(id_1)

    def test_generate_sparse_id_determinism_and_default(self):
        parent_id = "test-parent-id-123"

        id_default = generate_sparse_id(parent_id=parent_id)
        id_explicit_bm25 = generate_sparse_id(parent_id=parent_id, model_name="bm25")
        id_splade = generate_sparse_id(parent_id=parent_id, model_name="splade-v3")

        assert id_default == id_explicit_bm25
        assert id_default != id_splade
        assert is_valid_uuid(id_default)


class TestUUIDGeneratorsCollisionsAndIsolation:
    def test_chunk_index_prevents_collision_on_same_content(self):
        url = "https://example.edu/policy"
        content = "Identical repeated footer text."

        chunk_0_id = generate_chunk_id(source_url=url, chunk_index=0, content=content)
        chunk_1_id = generate_chunk_id(source_url=url, chunk_index=1, content=content)

        assert chunk_0_id != chunk_1_id

    def test_different_namespaces_prevent_cross_type_collision(self):
        same_str = "https://example.edu/test"

        doc_id = generate_doc_id(source_url=same_str)
        # Even if a raw seed shares the exact same string, prefixing prevents hash collision
        raw_id = generate_uuid(seed=same_str)

        assert doc_id != raw_id

    def test_keyword_only_enforcement(self):
        """Ensures that positional arguments are rejected at runtime."""
        with pytest.raises(TypeError):
            generate_uuid("positional_seed")  # type: ignore

        with pytest.raises(TypeError):
            generate_doc_id("https://example.edu")  # type: ignore

        with pytest.raises(TypeError):
            generate_chunk_id("https://example.edu", 0, "content")  # type: ignore