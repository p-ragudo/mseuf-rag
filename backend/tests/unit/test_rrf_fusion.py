import pytest
from unittest.mock import Mock
from app.services.query_pipeline.query_pipeline import QueryPipeline

def test_rrf_accumulates_dense_question_scores_for_parent_chunk():
    pipeline = QueryPipeline()

    # Chunk A matched by 2 different synthetic questions (ranks 0 and 1)
    hit_q1 = Mock(id="q1", score=0.9, payload={"parent_chunk_id": "chunk_A", "question_text": "How much is tuition?"})
    hit_q2 = Mock(id="q2", score=0.85, payload={"parent_chunk_id": "chunk_A", "question_text": "What are the school fees?"})
    
    # Chunk B matched by only 1 question (rank 2)
    hit_q3 = Mock(id="q3", score=0.80, payload={"parent_chunk_id": "chunk_B", "question_text": "Where is the campus located?"})

    dense_hits = [hit_q1, hit_q2, hit_q3]
    sparse_hits = []

    fused = pipeline._reciprocal_rank_fusion(dense_hits, sparse_hits, k=60)

    # Chunk A should rank first with accumulated score: 1/(60+0+1) + 1/(60+1+1)
    assert fused[0][0] == "chunk_A"
    assert len(fused[0][3]) == 2  # 2 matched questions tracked in telemetry
    expected_score_a = (1.0 / 61.0) + (1.0 / 62.0)
    assert pytest.approx(fused[0][1], rel=1e-4) == expected_score_a

    # Chunk B should rank second with: 1/(60+2+1)
    assert fused[1][0] == "chunk_B"
    expected_score_b = 1.0 / 63.0
    assert pytest.approx(fused[1][1], rel=1e-4) == expected_score_b