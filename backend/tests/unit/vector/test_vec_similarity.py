import os
import numpy as np

# Bypass HF Hub remote checks for speed
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


from app.core.config import settings
from sentence_transformers import SentenceTransformer
from app.services.cache.vectorizer import get_cache_vectorizer


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Computes standard cosine similarity between two 1D vectors."""
    dot_product = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot_product / (norm_a * norm_b))


def main():
    model_name = settings.embedding_model
    cache_threshold = settings.semantic_cache_threshold

    print("=" * 60)
    print("VECTOR SIMILARITY & DISTANCE DIAGNOSTIC")
    print("=" * 60)
    print(f"Model:           {model_name}")
    print(f"Cache Threshold: {cache_threshold} (Max allowed distance for hit)")
    print("=" * 60)

    # 1. Test Queries
    base_query = "How do I shift to another program?"
    similar_query = "What is the procedure for shifting to a different course?"
    unrelated_query = "Where is the campus cafeteria?"

    # 2. Raw SentenceTransformer Encoding & Math Check
    print("\n--- 1. Raw SentenceTransformer Math Check ---")
    st_model = SentenceTransformer(model_name)

    vec_base = st_model.encode(base_query)
    vec_similar = st_model.encode(similar_query)
    vec_unrelated = st_model.encode(unrelated_query)

    print(f"Vector Dimensions: {len(vec_base)}")

    # Pair A: Base vs Similar
    sim_a = cosine_similarity(vec_base, vec_similar)
    dist_a = 1.0 - sim_a
    hit_a = dist_a <= cache_threshold

    print(f"\n[Pair A: Base vs Similar]")
    print(f"  Q1: '{base_query}'")
    print(f"  Q2: '{similar_query}'")
    print(f"  -> Cosine Similarity: {sim_a:.4f} ({sim_a * 100:.2f}%)")
    print(f"  -> Cosine Distance:   {dist_a:.4f}")
    print(f"  -> Cache Hit Status:  {'✓ HIT' if hit_a else '✗ MISS'} (Threshold: <= {cache_threshold})")

    # Pair B: Base vs Unrelated
    sim_b = cosine_similarity(vec_base, vec_unrelated)
    dist_b = 1.0 - sim_b
    hit_b = dist_b <= cache_threshold

    print(f"\n[Pair B: Base vs Unrelated]")
    print(f"  Q1: '{base_query}'")
    print(f"  Q2: '{unrelated_query}'")
    print(f"  -> Cosine Similarity: {sim_b:.4f} ({sim_b * 100:.2f}%)")
    print(f"  -> Cosine Distance:   {dist_b:.4f}")
    print(f"  -> Cache Hit Status:  {'✗ UNEXPECTED HIT' if hit_b else '✓ MISS (Expected)'}")

    # 3. RedisVL Vectorizer Check (Verify output parity)
    print("\n--- 2. RedisVL Vectorizer Output Parity ---")
    vectorizer = get_cache_vectorizer()

    rvl_vec_base = np.array(vectorizer.embed(base_query), dtype=np.float32)
    rvl_vec_similar = np.array(vectorizer.embed(similar_query), dtype=np.float32)

    rvl_sim = cosine_similarity(rvl_vec_base, rvl_vec_similar)
    rvl_dist = 1.0 - rvl_sim

    print(f"RedisVL Cosine Similarity: {rvl_sim:.4f}")
    print(f"RedisVL Cosine Distance:   {rvl_dist:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()