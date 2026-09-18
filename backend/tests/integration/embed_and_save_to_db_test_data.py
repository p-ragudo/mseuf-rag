import asyncio
import uuid
from typing import List
import pytest

from app.core.config import settings
from app.services.embeddings.factory import get_embedder
from app.services.vector_db.factory import get_vector_db
from app.services.vector_db.schema import VectorPoint
from app.services.llm_qgen.schema import GeneratedQuestion, RawChunk
from scripts.sample_data import SAMPLE_CHUNKS


class PipelineIngestionTester:
    """Orchestrates test pipeline using factory methods:
    Inputs -> Embed -> Store in Dual Collections (Questions & Chunks)
    """

    def __init__(self):
        self.embedder = get_embedder()
        self.vdb = get_vector_db()

        self.questions_collection = settings.dense_collection_name
        self.chunks_collection = settings.chunk_collection_name

    async def setup_collections(self) -> None:
        """Initializes dense question collection and unvectorized payload chunk collection."""
        vector_size = self.embedder.dimension

        # Dense collection for embedded questions
        await self.vdb.create_collection_if_not_exists(
            collection_name=self.questions_collection,
            vector_size=vector_size,
            distance="Cosine",
        )

        # Payload-only collection for raw text chunks
        await self.vdb.create_collection_if_not_exists(
            collection_name=self.chunks_collection,
            vector_size=None,
        )

    async def ingest_pipeline(
        self,
        chunks: List[RawChunk],
        questions: List[GeneratedQuestion],
    ) -> None:
        """Embeds questions and stores both questions and chunks into distinct collections."""
        # 1. Upsert unvectorized chunks into payload-only collection
        chunk_records = [
            {
                "id": chunk.id,
                "doc_id": chunk.doc_id,
                "source_url": chunk.source_url,
                "title": chunk.title,
                "content": chunk.content,
                "tags": chunk.tags,
            }
            for chunk in chunks
        ]
        await self.vdb.upsert_payload_only(
            collection_name=self.chunks_collection,
            records=chunk_records,
            id_key="id",
        )

        # 2. Embed generated questions and upsert into dense vector collection
        if not questions:
            return

        question_texts = [q.content for q in questions]
        embedding_results = self.embedder.embed(question_texts)

        vector_points = [
            VectorPoint(
                id=q.id,
                vector=emb.values,
                payload={
                    "chunk_id": q.chunk_id,
                    "content": q.content,
                    "tags": q.tags,
                },
            )
            for q, emb in zip(questions, embedding_results)
        ]

        await self.vdb.upsert_points(
            collection_name=self.questions_collection,
            points=vector_points,
        )


# =====================================================================
# Ingestion Verification Suite
# =====================================================================

@pytest.mark.asyncio
async def test_embed_and_dual_store_pipeline():
    tester = PipelineIngestionTester()

    # 1. Ensure collections exist
    await tester.setup_collections()

    # 2. Prepare sample data
    test_chunks = SAMPLE_CHUNKS
    test_questions = [
        GeneratedQuestion(
            id=str(uuid.uuid4()),
            chunk_id=test_chunks[0].id,
            content="When is the deadline to submit the program shifting form?",
            tags=test_chunks[0].tags,
        ),
        GeneratedQuestion(
            id=str(uuid.uuid4()),
            chunk_id=test_chunks[0].id,
            content="Where should the approved Shifting Form be submitted?",
            tags=test_chunks[0].tags,
        ),
        GeneratedQuestion(
            id=str(uuid.uuid4()),
            chunk_id=test_chunks[1].id,
            content="What minimum GWA is required to keep an academic scholarship?",
            tags=test_chunks[1].tags,
        ),
    ]

    # 3. Execute ingestion
    await tester.ingest_pipeline(chunks=test_chunks, questions=test_questions)

    # 4. Verify Raw Chunks in chunks_collection
    retrieved_chunks = await tester.vdb.client.retrieve(
        collection_name=tester.chunks_collection,
        ids=[c.id for c in test_chunks],
        with_payload=True,
    )
    assert len(retrieved_chunks) == len(test_chunks), (
        f"Expected {len(test_chunks)} chunks, found {len(retrieved_chunks)}"
    )
    retrieved_chunk_ids = {str(p.id) for p in retrieved_chunks}
    for chunk in test_chunks:
        assert chunk.id in retrieved_chunk_ids

    # 5. Verify Questions in questions_collection with vectors & payloads
    try:
        retrieved_questions = await tester.vdb.client.retrieve(
            collection_name=tester.questions_collection,
            ids=[q.id for q in test_questions],
            with_payload=True,
            with_vectors=True,
        )
    except TypeError:
        retrieved_questions = await tester.vdb.client.retrieve(
            collection_name=tester.questions_collection,
            ids=[q.id for q in test_questions],
            with_payload=True,
            with_vector=True,
        )

    assert len(retrieved_questions) == len(test_questions), (
        f"Expected {len(test_questions)} questions, found {len(retrieved_questions)}"
    )

    for q_record in retrieved_questions:
        assert "chunk_id" in q_record.payload
        assert "content" in q_record.payload
        # Verify vector values exist and match the configured dimension
        vector = q_record.vector
        if isinstance(vector, dict):
            # Handle named vector dict format if configured
            vector = next(iter(vector.values()))
        assert len(vector) == tester.embedder.dimension


if __name__ == "__main__":
    asyncio.run(test_embed_and_dual_store_pipeline())
    print("Ingestion test completed successfully: Chunks and Vectorized Questions persisted.")