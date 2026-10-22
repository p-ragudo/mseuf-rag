# RAG Evaluation Suite - Walkthrough

Location: `backend/evaluation/`. Everything here is **read-only against production**. Run all commands from `backend/`.

## 0. Quickstart (The 3-Step Evaluation Sweep)

```bash
cd backend

# Step 1: Structure the 3 datasets (150 stratified/tiered Synthetic + 63 hydrated Official FAQs + 71 Real Users = 284 total)
uv run python -m evaluation.generate_ground_truth --org-id 1 --overwrite

# Step 2: Run the Multilingual Blind Query Generator (50 English, 50 Tagalog, 50 Taglish for synthetic; 21 each for FAQs)
uv run python -m evaluation.blind_query_generator --org-id 1

# Step 3: Run the complete multi-level evaluation across all 284 queries
uv run python -m evaluation.run_evaluation --org-id 1 \
  --filename ground_truth_150_blind.jsonl ground_truth_faqs_63_blind.jsonl queries_real_users_71.jsonl \
  --use-blind-queries --stage all --allow-prod-read
```

If `.env` points at the PRODUCTION Qdrant cluster, `--allow-prod-read` is required. 
Results are saved to: `evaluation/data/org_<id>/runs/<timestamp>/` (`report.md`, `summary.json`, `rows.csv`, `rows.jsonl`). Old runs are never overwritten.

---

## 1. What Each Architecture Upgrade Does

| Component | Purpose / Problem Addressed |
|---|---|
| **Stratified & Tiered Datasets (150 Synthetic + 63 FAQs + 71 Real Users)** | Balances domain clusters (`faqs_procedures`, `specs_programs`, `policies_announcements`) across `easy` (1-hop), `medium` (2-3 chunk cross-ref), and `hard` (multi-hop/calculation) tiers. |
| **Multilingual Generation (English, Tagalog, Taglish)** | Rotates synthetic and blind queries across 3 languages (~33.3% each) to rigorously evaluate cross-lingual retrieval and code-switching synthesis. |
| **Blind Query Generation** | Strips chunk context and base queries during query creation, forcing the LLM to write natural user questions while obeying "taboo phrase" constraints against copying official headings. |
| **Multi-Gold Retrieval Metrics (`Recall@k`, `All-Hit@k`, `Precision@k`)** | Correctly scores multi-chunk dependencies instead of scoring 1/3 retrieved chunks as a binary "hit". |
| **Reference-Free RAG Triad** | Evaluates the 71 unlabeled real-user queries using LLM-as-a-judge Groundedness, Helpfulness, and Context Sufficiency without needing pre-written ground truth. |
| **Semantic Answer Similarity** | Complements token F1, BLEU-4 (with Chen & Cherry smoothing), and ROUGE-L by calculating dense embedding cosine similarity between predicted and reference answers. |

---

## 2. How Production is Protected (Read-Only Guarantees)

Every write path is closed in code (`safety.py`) and verified at startup:

1. **Postgres**: A SQLAlchemy `before_cursor_execute` hook intercepts and blocks any `INSERT`, `UPDATE`, `DELETE`, `DDL`, `TRUNCATE`, or `COPY` statement before it reaches the database. Verified via `selftest_postgres_guard()`.
2. **Qdrant**: `pipeline.vector_db` is wrapped in `ReadOnlyVectorDB`, exposing only `search`, `search_sparse`, and `close`. Any write attempt raises `ProductionWriteBlocked`.
3. **Redis Semantic Cache**: `build_safe_pipeline()` substitutes the cache factory with a strict no-op `NoOpSemanticCache` before `QueryPipeline()` initializes, ensuring the real cache is never read from or written to.
4. **App State**: The suite calls pipeline internals directly rather than HTTP routes, ensuring zero interaction with `session_messages`, stats, or response log tables.
5. **File System**: All generated datasets, intermediate states, and evaluation reports are strictly sandboxed inside `backend/evaluation/data/`.

---

## 3. What is Measured, Stage by Stage

```
query -> embed (dense) + classify intent (campus) + BM25 (sparse)
      -> Qdrant: dense over synthetic QUESTION vectors   -> [A] dense ranking
                 sparse BM25 over chunk text             -> [B] sparse ranking
      -> RRF fusion (pool of >= 25 chunks)               -> [C] rrf ranking
      -> cross-encoder rerank (keeps 2*k)                -> [D] rerank ranking
      -> score threshold + temporal resolution + top-k   -> [E] final ranking
      -> Postgres small-to-big expansion (+/-1 chunk)    -> [F] expanded contexts read by LLM
      -> answer LLM                                      -> answer
```

- **Retrieval Stage (`--stage retrieval`)**: Records ranks at stages A–E and checks `ctx_hit` at stage F. Reports Hit@1, Hit@$k$, Precision@$k$, Recall@$k$, All-Hit@$k$, MRR@$k$, and nDCG@$k$ with cluster bootstrap 95% CIs.
- **Answer Stage (`--stage answer` or `all`)**: Computes lexical overlap (Token F1, smoothed BLEU-4, ROUGE-1/2/L), semantic embedding similarity, reference-backed custom judge scores (Groundedness, Completeness, Helpfulness, Context Sufficiency), and Ragas metrics.
- **Real-User Telemetry**: Evaluates the 71 unlabelled queries using reference-free RAG Triad metrics and fallback/abstention rates.

---

## 4. Verification and Troubleshooting

- `Refusing to run: ... PRODUCTION Qdrant` -> Use a staging Qdrant cluster (`USE_TEST_QDRANT_DB=true`) or pass `--allow-prod-read`.
- `ProductionWriteBlocked` -> Good! A write attempt was successfully intercepted and blocked.
- Parity Check Failures -> If `pipeline_inspector.py` drifts from production `QueryPipeline.execute()`, the suite halts safely. Update `pipeline_inspector.py` to match any recent production routing updates.