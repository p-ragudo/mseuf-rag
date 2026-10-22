# RAG evaluation suite - walkthrough

Location: `backend/evaluation/`. Everything here is **read-only against production**. Run all commands from `backend/`.

## 0. The 10-line version

```bash
cd backend

# Step 1: Structure the 3 datasets (100 stratified/tiered Synthetic + 21 hydrated Official FAQs + 71 Real Users = 192 total)
uv run python -m evaluation.generate_ground_truth --org-id 1 --overwrite

# Step 2: Run the Blind Query Generator on the 100 Synthetic pairs (and 21 FAQs)
uv run python -m evaluation.blind_query_generator --org-id 1

# Step 3: Run the complete evaluation across all 192 queries (100 Blind Synthetic + 21 Blind FAQs + 71 Real Users)
uv run python -m evaluation.run_evaluation --org-id 1 \
  --filename ground_truth_100_blind.jsonl ground_truth_faqs_21_blind.jsonl queries_real_users_71.jsonl \
  --use-blind-queries --stage all --allow-prod-read
```

If `.env` points at the PRODUCTION Qdrant, add `--allow-prod-read` (reads only; see section 2).
Results: `evaluation/data/org_<id>/runs/<timestamp>/report.md` (paper-ready tables), `summary.json`, `rows.csv`, `rows.jsonl`. Old runs are never overwritten.

## 1. What was wrong before and what each fix does

| Problem in the old suite | Why it made numbers untrustworthy | Fix |
|---|---|---|
| `tenant_isolation_pass_rate` was hardcoded `True` | Always 1.0, tests nothing | Removed. `safety.py` blocks cross-system writes; isolation is not claimed. (Optional real test: section 9.) |
| Hit@k fell back to **URL match** when the chunk was missed | Any other chunk from the same page counted as a hit, while a gold chunk at rank 8 counted as a miss | Chunk-level only. URL rank kept as a diagnostic column. |
| "Reranker lift" used the final list (threshold + temporal + top-k) | Lift was not the reranker alone; `rank_delta` set to 0 when a rank was missing, hiding harm | Reranker isolated (`post_rerank_candidates`), paired comparison with **rescued / harmed** counts and McNemar p. Temporal effect reported separately. |
| Pre-MRR used the 25-pool, post-MRR only 5 | Unfair comparison | All metrics use `@k` consistently |
| Test questions and the dense index came from the same kind of LLM prompt on the same chunk | Retrieval was matching paraphrases of questions it was built from -> optimistic | Second **colloquial** set on the **same gold chunks** (different prompt, optional different model) + optional **human** set + **negative** set. The gap between sets is a finding. |
| Only chunks that already had generated questions were sampled | Survivorship | Kept for tractability, but stated as a limitation; human set removes it |
| Single-chunk gold, exact duplicates counted as misses | Penalised correct retrieval | Exact same-campus duplicate chunks are added as equally valid gold |
| Judge saw `[:6000]` chars, production feeds up to 16000 | Groundedness/sufficiency unfairly low | Full contexts, one item per judge call |
| 5 items per judge prompt | Cross-contamination | One item per call |
| Failed judge/Ragas rows silently dropped from means | Metrics averaged over different subsets | `n` shown per metric; failures counted in `summary.json` |
| Refusals counted as "1.0 grounded", fallbacks mixed into answer means | Flattered averages | Fallbacks reported separately; completeness shown also with fallback = 0 |
| No uncertainty | n is about 80 per tenant | Bootstrap 95% CIs that resample **gold chunks** (not rows) |
| BLEU/ROUGE as headline | Style overlap of two LLM texts | Kept in CSV, only token recall / F1 / ROUGE-L in the report as weak signals |
| Hallucination on unanswerable questions untested | The most important chatbot failure | Negative set + abstention judge + reranker-score AUC/threshold |
| Dataset could be stale | Re-scrape changes chunk text | Gold chunk content hash re-checked in Postgres; stale records skipped and counted |

## 2. How production is protected

An evaluation that "probably doesn't write" is not enough, so every write path is closed in code (`safety.py`) and verified at startup:

1. **Postgres**: a SQLAlchemy `before_cursor_execute` hook raises `ProductionWriteBlocked` for INSERT / UPDATE / DELETE / DDL / TRUNCATE / GRANT / COPY / writing CTEs before the statement is sent. At startup `selftest_postgres_guard()` tries a write and confirms it is blocked (the statement never reaches the database).
2. **Qdrant**: `pipeline.vector_db` is wrapped in `ReadOnlyVectorDB`, which exposes only `search`, `search_sparse`, `close`. `upsert_points`, `delete_points`, `create_collection_if_not_exists` and the raw `.client` raise `ProductionWriteBlocked`. Checked at startup.
3. **Redis semantic cache**: `RedisSemanticCache.__init__` uses `overwrite=True`, so merely constructing it re-creates the cache index. `build_safe_pipeline()` temporarily replaces the factory with a no-op **before** `QueryPipeline()` runs, so the real cache is never created, read, or written. It then asserts the swap worked.
4. **App state**: the suite calls pipeline internals, never the HTTP routes, so no `session_messages`, stats or response rows are written.
5. **Environment banner**: prints Qdrant target (TEST/PRODUCTION), collection, Postgres host, models. If it is PRODUCTION you must pass `--allow-prod-read`. Best practice: point `.env` at a staging/test Qdrant (`USE_TEST_QDRANT_DB`) and, if you can, a read-only Postgres user in `DATABASE_URL` (belt and braces).
6. **Files**: the only things written are under `backend/evaluation/data/`.

What it still does that touches shared resources: Gemini API calls (quota/cost) and read load on Postgres/Qdrant. It runs sequentially to keep that small.

## 3. What is measured, stage by stage

The production query path, and where each measurement taps in:

```
query -> embed (dense) + classify intent (campus) + BM25 (sparse)
      -> Qdrant: dense over synthetic QUESTION vectors   -> [A] dense ranking   (question hits collapsed to chunks)
                 sparse BM25 over chunk text             -> [B] sparse ranking
      -> RRF fusion (pool of >= 25 chunks)               -> [C] rrf ranking
      -> cross-encoder rerank (keeps 2*k)                -> [D] rerank ranking  (reranker alone)
      -> score threshold + temporal resolution + top-k   -> [E] final ranking   (what production keeps)
      -> Postgres small-to-big expansion (+/-1 chunk)    -> [F] contexts the answer LLM reads
      -> answer LLM                                      -> answer
```

**Retrieval test (`--stage retrieval`, no answer generation).** For every answerable query it records the rank of the gold chunk at A-E and whether the gold text is inside the final contexts (F).
- Hit@1, Hit@k, MRR@k, nDCG@k with CIs per stage. Comparing A / B / C answers "does hybrid beat dense or sparse alone?". Comparing C -> D answers "does the reranker help?" (paired). D -> E isolates the temporal/threshold step.
- "Gold anywhere in list" at C is the reranker's ceiling: it cannot recover what was never in the pool.
- `gold_in_context` (F) is the end-to-end retrieval number: did the LLM even have the evidence? Anchor matching uses 3 text anchors per gold chunk (>= 2 of 3 must appear), so expansion/merging does not break it.
- `final_hit_but_not_in_context` should be about 0; if not, the expander or the matcher is losing evidence.

**Answer test (`--stage answer` or `all`).** Only for rows the pipeline answered and that have a reference:
- Custom judge (0 / .25 / .5 / .75 / 1): groundedness, completeness vs reference, helpfulness, context_sufficiency. One item per call, temperature 0.
- Ragas: faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness. `context_precision` is computed on expanded contexts (neighbours included) so it is structurally lower than classic top-k precision; do not compare it with papers.
- Judge agreement (section 6 of the report): Spearman rho between faithfulness/groundedness, answer_correctness/completeness, context_recall/context_sufficiency, answer_relevancy/helpfulness. Low rho means the judges disagree; do not over-interpret either.
- Lexical (token recall/F1, ROUGE-L): weak sanity signals only.

**Abstention test (set `negative`).** Off-topic questions plus plausible-but-absent ones. Correct behaviour is a refusal. Reports abstention rate and unsupported-answer rate, the AUC of the top reranker score for separating answerable from unanswerable, and a suggested `reranker_score_threshold` (currently unset in your settings). Treat the suggested threshold as a hypothesis to validate, not a setting to ship.

**Parity check.** Before scoring, `--parity-check N` runs N queries through the real `QueryPipeline.execute()` and through the inspector and requires identical contexts. If production code changes and the inspector drifts, you find out instead of silently measuring a stale copy.

## 4. The datasets

| set | how made | what it tells you | caveat |
|---|---|---|---|
| `synthetic_standard` | LLM, formal, 1-2 Qs per sampled chunk | Regression baseline | In-distribution with the question index -> optimistic |
| `synthetic_colloquial` | LLM, informal/Taglish, 1 Q per same chunk, different prompt (and model via `--colloquial-model`) | Robustness to phrasing; standard minus colloquial = how much of your score is easy phrasing | Still LLM-written |
| `negative` | 6 fixed off-topic + N LLM plausible-absent | Hallucination / abstention, threshold tuning | `plausible_absent` may accidentally be answerable: read them once (`needs_review`) |
| `human` | CSV via `import_human_queries.py` | The only set independent of any LLM | Needs people; even 30 queries are valuable |

Human CSV format (people only write the question; you pick a distinctive phrase from the official page):
```
query,gold_phrase,reference_answer
"magkano tuition ng BSCS?","Tuition and other fees per semester",""
```
`uv run python -m evaluation.import_human_queries --org-id 1 --csv queries.csv` then run with `--filename ground_truth_v2.jsonl ground_truth_human.jsonl`.

## 5. How to read the numbers (what you may claim)

- **"Hit@5 = 0.91 [0.84-0.96] on synthetic_standard"** -> claim: retrieval finds the source chunk for well-formed synthetic questions. Do not claim real-world accuracy.
- **colloquial lower than standard** -> evidence the standard score was inflated by phrasing; report both.
- **Reranker: rescued 9, harmed 2, McNemar p = 0.07** -> direction is positive but not conclusive at this n. Say that.
- **gold_in_context vs final Hit@k** -> end-to-end retrieval vs ranking.
- **Faithfulness/groundedness high** -> answers stay within the retrieved text (as judged by an LLM). It is not the same as the website being correct.
- **Negatives: abstained low** -> real hallucination risk, a finding rather than a bug in the test.

## 6. Time-boxed plan for tonight

1. Put the files in place (10 min). Run **A** (retrieval only, your existing dataset) and read `report.md`.
2. If time: **B** (about 130 queries, retrieval only) - this gives standard vs colloquial and the negative set.
3. Only then **C**, with `--skip-ragas` if time is tight (custom judges alone are enough for the paper).
4. Write the limitations paragraph (section 7). Do not wait for human queries; add them as future work or if teammates deliver.

## 7. Wording for the paper

> Ground truth was generated by an LLM from the same document chunks that were indexed and was not verified by institutional staff. Results are therefore in-distribution and should be read as upper-bound, comparative indicators rather than absolute accuracy. To reduce phrasing bias we report a second, colloquially phrased set on the same gold chunks and a set of unanswerable questions. Retrieval is scored at chunk level; intervals are 95% bootstrap CIs resampling gold chunks (n = X queries, Y chunks). Answer-quality scores are LLM-judged against LLM-written references (judge model: M) and are subject to self-preference bias.

## 8. What this suite still does NOT prove

- Real-user accuracy or satisfaction (needs human queries / logs).
- That the scraped content matches what offices actually say (needs staff verification).
- Semantic-cache correctness (hit precision, stale hits): the cache is deliberately bypassed.
- Multi-turn / follow-up behaviour, load/latency under concurrency, ingestion/scraper quality.
- Near-duplicate (not exact) chunks across pages still count as misses.
- Cross-tenant isolation. Optional test: run tenant A's queries with `group_id = B` and assert zero returned payloads have `group_id = A` (not implemented here).

## 9. Troubleshooting

- `Refusing to run: ... PRODUCTION Qdrant` -> use a test cluster or add `--allow-prod-read`.
- `ProductionWriteBlocked` -> good, something tried to write; the message names the statement/method.
- Model-name errors -> defaults keep your previous `gemini-3.8-flash`; override with `--judge-model` / `--curator-model`.
- Ragas error -> the run still saves retrieval + custom-judge results (`ragas_error` in `summary.json`); rerun with `--skip-ragas`.
- A hung call -> `compat.py` disables asyncio timeouts (needed on Python 3.14 + Ragas); Ctrl+C and rerun, or `EVAL_SKIP_COMPAT=1` for the retrieval stage if it works without.
- Many stale records -> content was re-scraped after dataset creation; regenerate with `generate_ground_truth`.

## 10. Verification status of this code

Tested offline with stubbed app modules: the Postgres guard (7 write forms blocked, SELECTs pass), the "real cache never instantiated" path, the read-only Qdrant proxy, the inspector's stage rankings, build_row, the metrics (rank, anchors, bootstrap, McNemar, AUC, Spearman) and the report. **Not run** against your real Postgres / Qdrant / Gemini / Ragas versions: run step A first and fix any import or signature mismatch it prints.
