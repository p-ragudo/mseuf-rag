import pytest
from app.services.reranker.schema import RerankResult
from app.services.query_pipeline.temporal_resolver import resolve_temporal_conflicts

def test_resolve_temporal_conflicts_prunes_older_academic_period():
    newer_chunk = RerankResult(
        chunk_id="c_2026",
        content="Tuition for AY 2026-2027 is 35,000 PHP per term.",
        initial_score=0.9,
        rerank_score=0.92,
        payload={
            "source_url": "https://uni.edu/fees",
            "heading_path": "Admissions > Tuition Fees",
            "doc_period": 2026,
            "campus": "main",
        },
    )
    older_chunk = RerankResult(
        chunk_id="c_2024",
        content="Tuition for AY 2024-2025 is 30,000 PHP per term.",
        initial_score=0.88,
        rerank_score=0.89,
        payload={
            "source_url": "https://uni.edu/fees",
            "heading_path": "Admissions > Tuition Fees",
            "doc_period": 2024,
            "campus": "main",
        },
    )

    kept, superseded = resolve_temporal_conflicts("What is the tuition fee?", [newer_chunk, older_chunk])
    assert len(kept) == 1
    assert kept[0].chunk_id == "c_2026"
    assert len(superseded) == 1
    assert "newer academic period" in superseded[0].reason

def test_resolve_temporal_conflicts_honors_explicit_year_in_query():
    chunk_2026 = RerankResult(
        chunk_id="c_2026",
        content="AY 2026-2027 fees: 35k.",
        initial_score=0.9,
        rerank_score=0.92,
        payload={"source_url": "https://uni.edu/fees", "doc_period": 2026, "campus": "main"},
    )
    chunk_2024 = RerankResult(
        chunk_id="c_2024",
        content="AY 2024-2025 fees: 30k.",
        initial_score=0.88,
        rerank_score=0.89,
        payload={"source_url": "https://uni.edu/fees", "doc_period": 2024, "campus": "main"},
    )

    # User explicitly asks for 2024
    kept, superseded = resolve_temporal_conflicts("tuition fee 2024", [chunk_2026, chunk_2024])
    assert len(kept) == 1
    assert kept[0].chunk_id == "c_2024"
    assert "query requests 2024-2025" in superseded[0].reason