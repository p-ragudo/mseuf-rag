# RAG System Architecture & Agent Context

> Last audited against the backend code: 2026-10-06.
> Status tags: **[IMPLEMENTED]** matches the code, **[PARTIAL]** exists but incomplete or flawed, **[PLANNED]** designed but not built.
> Where this file and the code disagree, the code wins. Fix the code or update this file in the same change.

## 1. System Overview

A **multi-tenant Retrieval-Augmented Generation (RAG) service**. Organizations (tenants) register websites[cite: 1]. The system scrapes them, chunks the content, and indexes it for semantic question answering over their own content only[cite: 1].

The core idea is **question-augmented indexing**[cite: 1]. For every chunk, an LLM generates 3-5 questions the chunk answers[cite: 1]. Each question becomes its own Qdrant point with a **dense vector of the question**[cite: 1]. Each of those points also carries a **BM25 sparse vector of the parent chunk text**[cite: 1]. The hypothesis is that user queries sit closer to generated questions than to raw chunk text in embedding space[cite: 1].

**Thesis validation**: does question-augmented dense retrieval beat chunk-only retrieval? (See section 11 for a methodological gap in the current baseline.)[cite: 1]

## 2. Tech Stack

| Concern | Choice |
|---|---|
| API | FastAPI, async everywhere[cite: 1] |
| Relational store | PostgreSQL via SQLAlchemy 2.x async (source of truth for pages, chunks, questions, sync flags)[cite: 1] |
| Vector DB | Qdrant (single master collection, default name from settings)[cite: 1, 6] |
| Dense embeddings | Gemini embeddings via `EmbedderFactory` (or local FastEmbed/SentenceTransformers/Ollama; dimension defaults to 768 / 3072)[cite: 1, 2] |
| Sparse embeddings | fastembed `Qdrant/bm25`, with the IDF modifier applied server-side by Qdrant[cite: 1, 2, 10] |
| Cross-encoder reranker | fastembed `TextCrossEncoder` (default `Xenova/ms-marco-MiniLM-L-12-v2`), with FlashRank and PyTorch Transformers alternatives[cite: 6, 8] |
| Question generation | Gemini (`LLM_QGEN_*` settings), temperature 0.2, batches of 10 chunks per prompt[cite: 1, 5] |
| Answer synthesis | Gemini (`LLM_QA_*` settings), temperature 0.3, max 2048 output tokens[cite: 1, 4] |
| Intent classifier | Gemini `gemini-3.5-flash-lite`, structured JSON output via Pydantic schema[cite: 7] |
| Semantic cache | Redis via RedisVL `SemanticCache` (in-memory implementation for tests), tenant- and campus-scoped[cite: 1, 7, 9] |
| Scraping | crawl4ai, httpx, sitemap and robots.txt discovery[cite: 1, 3] |
| Chunking | Structure-aware markdown chunker (`chunker.py` using heading hierarchy, atomic blocks, and section packing)[cite: 3] |
| Auth | JWT (HS256, python-jose), bcrypt via pwdlib[cite: 1, 6] |
| Ops | Telegram long-poll bot for `/scrape` and `/status`[cite: 1, 6] |

All external providers sit behind an abstract base plus a factory (`get_vector_db`, `get_embedder`, `get_sparse_embedder`, `get_reranker`, `get_question_generator`, `get_qa_synthesizer`, `get_semantic_cache`)[cite: 1, 2, 4, 5, 8, 9, 10]. Add new providers by registering them in the factory. Do not import provider classes directly in pipeline code[cite: 1].

## 3. Repository Layout

```text
backend/
  app/
    core/        config.py (pydantic-settings), database.py, security.py
    models/      user, org, org_member, website, website_schedule, scraped_page, chunk, generated_question
    routes/      auth, orgs, websites, ingest, query
    schemas/     tenant.py
    services/
      embeddings/        base, factory, gemini_embedder, sparse_embedder, fastembed_embedder, sentence_transformer_embedder, ollama_embedder, schema
      llm_qgen/          base_qgen, factory, gemini_provider, schema, sys_instructions
      llm_qa/            base_qa, factory, gemini_provider, schema, sys_instructions
      reranker/          base, factory, fastembed_provider, flashrank_provider, transformers_provider, schema
      semantic_cache/    base, factory, redis_cache, in_memory_cache, schemas
      vector_db/         base, factory, qdrant_provider, schema
      ingest_pipeline/   discovery, orchestrator, chunk, chunker, clean_markdown
      query_pipeline/    query_pipeline, intent_classifier, context_expander, schema
    utils/       uuid_generator.py, telegram_bot.py
    main.py
  scripts/
  tests/
```

## 4. Relational Data Model (PostgreSQL)

```text
users 1--* org_members *--1 orgs 1--* websites 1--1 website_scrape_schedules
                                       websites 1--* scraped_pages 1--* chunks 1--* generated_questions
```

| Table | Key fields |
|---|---|
| `orgs` | id, creator_id, name[cite: 1, 6] |
| `org_members` | (user_id, org_id) PK, `roles` string ("admin"/"member"), **roles are stored but not enforced across endpoints**[cite: 1, 6] |
| `websites` | id, org_id, url, `status` (PENDING/IN_PROGRESS/COMPLETED/FAILED), error_message[cite: 1, 6] |
| `website_scrape_schedules` | id, web_id (unique FK), interval_days, time_of_scrape, last/next_scraped_at. **No background scheduler consumes this yet** [PLANNED][cite: 1, 6] |
| `scraped_pages` | id, org_id, web_id, url, markdown_content, `status` (PENDING/IN_PROGRESS/COMPLETED/FAILED), retries, chunked_at. Unique (`org_id`, `web_id`, `url`)[cite: 1, 6] |
| `chunks` | id, page_id, content, token_count, has_qgen, chunk_index, section_id, heading_path, part_index, part_total, qgen_attempts[cite: 3, 6] |
| `generated_questions` | id, chunk_id, question, `is_synced_qdrant` (legacy), `is_synced_gemini`, `is_synced_gemini_768`, `is_synced_bge_m3`[cite: 6] |

Postgres holds the pipeline checkpoints[cite: 1]. Flags (`chunked_at`, `has_qgen`, `qgen_attempts`, and dynamic model sync columns) allow pipeline stages to safely resume after interruptions[cite: 1, 3, 6].

## 5. Qdrant Data Model

### Point structure (one point per generated question) [IMPLEMENTED][cite: 1]

```text
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ ID: UUIDv5 = f(parent chunk UUID, question text)                       â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚ DENSE (named: question_dense)   embedding of the QUESTION              â”‚
â”‚   on_disk=true, HNSW m=0 / payload_m=16, optional scalar/binary quant. â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚ SPARSE (named: chunk_sparse)    fastembed BM25 of the PARENT CHUNK     â”‚
â”‚   in-RAM index, Modifier.IDF (the same sparse vector is repeated on    â”‚
â”‚   every question point of that chunk)                                  â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚ PAYLOAD                                                                â”‚
â”‚   group_id         tenant key = str(org_id)   (indexed, is_tenant)     â”‚
â”‚   campus           sub-entity slug from URL   (keyword indexed)        â”‚
â”‚   web_id           Postgres website PK                                 â”‚
â”‚   parent_chunk_id  UUIDv5 of the chunk                                 â”‚
â”‚   question_text    the generated question                              â”‚
â”‚   chunk_text       full parent chunk text (duplicated per question)    â”‚
â”‚   source_url, page_id, chunk_id (Postgres PK)                          â”‚
â”‚   chunk_index, section_id, heading_path, part_index, part_total        â”‚
â”‚   doc_type         "ephemeral" | "evergreen"                           â”‚
â”‚   academic_level   shs | basic_ed | graduate | undergraduate           â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

For dense vectors we embed the **generated question**[cite: 1, 3]. For sparse vectors we encode the **chunk text** to preserve keywords[cite: 1, 3].

### Collection config

- **Single master collection** for all tenants dynamically configured via `settings.collection_name`[cite: 3, 6].
- **Payload partitioning**: every point has `group_id`[cite: 1, 3]. A keyword payload index on `group_id` is created with `is_tenant=True`[cite: 1, 10]. A keyword payload index is also created on `campus`[cite: 10].
- **HNSW**: `m=0` (no global graph) and `payload_m=16`, so graph edges are built per tenant[cite: 1, 10]. Every query includes a `group_id` filter[cite: 1, 7].
- **Quantization** (configurable via settings): scalar int8 (quantile 0.99) or binary[cite: 1, 6, 10]. Quantized vectors are kept in RAM and raw floats on disk[cite: 1, 10]. Search uses rescore with oversampling 2.0[cite: 1, 6, 10].

### ID scheme (`utils/uuid_generator.py`, namespace-scoped UUIDv5, deterministic)[cite: 1, 6]

- `doc_id = f(tenant, url)`[cite: 1, 6]
- `chunk_id = f(tenant, url, chunk_index, content)`[cite: 6]
- `question_id = f(chunk_id, question)`[cite: 6]
- `generate_sparse_id` is currently unused[cite: 1, 6].

## 6. Multi-Tenancy & Isolation

**Implemented**[cite: 1]
- Tenant = `orgs.id`[cite: 1]. In Qdrant it appears as `group_id=str(org_id)`[cite: 1, 3].
- Query path: JWT user, org lookup in PostgreSQL, mandatory `group_id` filter on both dense and sparse retrieval paths[cite: 1, 6, 7].
- Semantic cache is tenant-scoped and campus-scoped through a composite `org_id` tag filter (`<org_id>_<campus>`) on lookup and store[cite: 7, 9].
- The QA system prompt is parameterized with the org name (loaded from Postgres)[cite: 1, 4, 7].
- Ingest and website routes verify that the user belongs to the owning org via `OrgMember`[cite: 1, 6].
- Context expansion validates tenant isolation directly in SQL (`ScrapedPage.org_id == org_id`)[cite: 7].

**Not implemented / open**[cite: 1]
- No physical collection or shard isolation per tenant; isolation relies on payload filtering and tenant-aware HNSW graphs[cite: 1, 10].
- Role enforcement (`admin` vs `member`) is not enforced on mutate routes[cite: 1, 6]. Any org member can trigger ingestion or register websites[cite: 1, 6].
- Deleting an org or website cascades in Postgres but does not clean up Qdrant points[cite: 1, 6].
- Several heuristics retain university-specific naming assumptions (e.g. `classify_academic_level`, SHS strands)[cite: 1, 3].

## 7. Ingestion Pipeline

Triggered by `POST /ingest/run/{website_id}` (FastAPI `BackgroundTasks`) or by the Telegram `/scrape <id>` command[cite: 1, 6]. `run_full_pipeline` runs **five concurrent async workers** with `asyncio.Event` hand-offs, communicating through Postgres rows[cite: 1, 3].

```text
 discovery â”€â”€â–¶ scraper â”€â”€â–¶ chunker â”€â”€â–¶ qgen â”€â”€â–¶ qdrant_sync
 (sitemaps/    (crawl4ai   (clean +    (Gemini   (embed questions,
  robots, or    â†’ markdown  structure   batches   BM25 chunk, upsert
  1-level link  in PG)      chunker)    of 10)    points)
  crawl)
```

1. **Discovery** (`discovery.py`): robots.txt and sitemap discovery (recursive, cycle-safe, with fallback paths)[cite: 1, 3]. If none is found, falls back to 1-level internal link crawling from the homepage[cite: 1, 3]. Respects robots.txt, filters crawl traps, and inserts `scraped_pages` as PENDING (`ON CONFLICT DO NOTHING`)[cite: 1, 3].
2. **Scrape** (`orchestrator.py`): crawl4ai with structural noise tags excluded (`nav`, `footer`, `header`, `aside`, `form`, etc.)[cite: 1, 3]. Pages are fetched in batches of 10 and marked COMPLETED, or retried up to 3 times before marking FAILED[cite: 1, 3].
3. **Chunk** (`chunk.py`, `chunker.py`, `clean_markdown.py`): strips YAML frontmatter first, HTML tags, links, and noise phrases while preserving headings and lists[cite: 3]. Chunks via the structure-aware chunker (`chunker.py`) into atomic blocks (paragraphs, lists, tables, code) with breadcrumbs (`Admissions > Freshmen`), packing small sections and recording `chunk_index`, `section_id`, `part_index`, and `part_total`[cite: 3]. Replaces any old chunks for the page and updates `chunked_at`[cite: 1, 3].
4. **Question generation** (`orchestrator.py`, `gemini_provider.py`): 10 chunks per Gemini call, 3-5 questions each, strict grounding[cite: 1, 3, 5]. Chunks marked `has_qgen=True` only when questions are returned; unreturned or failed chunks increment `qgen_attempts` (up to 3 attempts) and parse errors raise rather than failing silently[cite: 3, 5].
5. **Qdrant sync** (`orchestrator.py`): in batches of 100 questions, generates dense embeddings with `task_type="RETRIEVAL_DOCUMENT"` and BM25 sparse vectors of the parent chunk text[cite: 3]. Upserts points into Qdrant (`wait=True`), and marks the dynamic active model column (e.g., `is_synced_gemini_768`) and `is_synced_qdrant` as True[cite: 3].

**Fault tolerance & State Management**:
- `run_full_pipeline` automatically reclaims stranded `IN_PROGRESS` pages on startup[cite: 3].
- Pipeline execution updates `Website.status` to `COMPLETED` or `FAILED` (with error message summary) upon termination[cite: 3].

## 8. Query Pipeline (Runtime)

`POST /query/{org_id}/`: calls `QueryPipeline.execute`[cite: 6, 7].

```text
[Query]
   â†“
[1. Dense query embedding]  (Gemini RETRIEVAL_QUERY, 768-dim)
   â†“
[2. Semantic cache fast-path check]  (Redis default org_id scope)
   â”œâ”€ HIT  â†’ return cached answer + contexts (source="cache")
   â””â”€ MISS â†“
[3. In parallel]  Intent classification (LLM)   +   BM25 sparse query embedding
   â†“
[4. Campus-scoped cache check]  (If campus detected and scope differs)
   â”œâ”€ HIT  â†’ return cached answer + contexts (source="cache")
   â””â”€ MISS â†“
[5. Hybrid retrieval]  dense (question_dense) âˆ¥ sparse (chunk_sparse),
                       limit = max(top_k * 6, 30) points
                       filter: group_id (mandatory) + campus (optional)
                       fallback: if campus returns 0 hits, retries tenant-wide
   â†“
[6. Chunk-level RRF fusion]  k=60, dense hits accumulate across questions,
                             sparse hit counted once per chunk
   â”œâ”€ no candidates â†’ fallback answer (source="fallback")
   â””â”€ candidates â†“
[7. Cross-encoder rerank]  Candidate pool = max(top_k * 4, 25).
                           Reranks chunks against query via FastEmbed / FlashRank / Transformers.
                           Filters by optional score_threshold.
   â”œâ”€ no candidates pass threshold â†’ fallback answer (source="fallback")
   â””â”€ candidates â†“
[8. Context expansion]  (context_expander.py) Small-to-big context expansion:
                        reloads sister parts of section_id and +/- 1 window neighbours
                        from PostgreSQL, joined in reading order up to 16,000 chars.
   â†“
[9. QA synthesis]  (Gemini QA LLM) Grounded answer synthesis using untrusted <document> tags.
   â†“
[10. Disambiguation note]  Append clarification note if query was flagged ambiguous.
   â†“
[11. Store in semantic cache]  (answer + sources + full contexts in metadata under final scope)
   â†“
[Return PipelineQueryResponse: answer, is_cached, source, sources, contexts]
```

## 9. Retrieval & Ranking Strategy

**Dense path**: query embedding via Gemini (`RETRIEVAL_QUERY`), searched against `question_dense` with mandatory `group_id` filter and optional `campus` filter[cite: 1, 7].

**Sparse path**: fastembed BM25 `query_embed` on query text, searched against `chunk_sparse` in Qdrant with identical payload filtering[cite: 2, 7, 10].

**Reciprocal Rank Fusion (`_reciprocal_rank_fusion`)**:
- Score formula: `1 / (k + rank + 1)` with `k=60`[cite: 1, 7].
- Dense hit scores accumulate across multiple matching questions for the same chunk[cite: 1, 7].
- Sparse hit scores are added once per parent chunk[cite: 1, 7].

**Cross-Encoder Reranker (`app/services/reranker/`) [IMPLEMENTED]**:
- Candidate pool sized at `max(top_k * 4, 25)` is sent to the reranker[cite: 7].
- Default provider is `FastEmbedReranker` using ONNX cross-encoders (`BAAI/bge-reranker-base` or `Xenova/ms-marco-MiniLM-L-12-v2`)[cite: 6, 8].
- Reranks fused candidates directly against the user query string[cite: 7, 8]. Supports `reranker_score_threshold` to gate out low-relevance results before answer generation[cite: 6, 7, 8].

**Context Expansion (`context_expander.py`) [IMPLEMENTED]**:
- Post-reranking, reloads full sections using `section_id` and window-adjacent chunks from PostgreSQL[cite: 7].
- Preserves procedural continuity (e.g. multi-step instructions) and merges adjacent chunks per page into unified context items[cite: 3, 7].

## 10. Other Components

**Semantic Cache** (`app/services/semantic_cache/`):
- Keyed on query vector[cite: 1, 7, 9]. Checked prior to heavy LLM and hybrid retrieval operations[cite: 7].
- Dynamic cache scoping: uses `org_id` base tag, and checks `org_id_campus` tag if a sub-entity is detected[cite: 7, 9].
- Stores answer, source URLs, and full context payload in metadata[cite: 1, 7, 9].

**Intent Classifier** (`app/services/query_pipeline/intent_classifier.py`):
- Uses Gemini (`gemini-3.5-flash-lite`) with structured JSON schema (`QueryIntent`)[cite: 7].
- Extracts `detected_sub_entity`, `detected_academic_level`, and `is_ambiguous`[cite: 7].
- Ambiguity appends a formatted note to the final synthesized response without aborting retrieval[cite: 7].

**QA Synthesizer** (`app/services/llm_qa/`):
- Formats contexts into XML-delimited `<document index="..." branch="...">` tags to protect against prompt injection from scraped text[cite: 4].
- System prompt enforces strict grounding, campus separation, and complete preservation of ordered procedures[cite: 1, 4].
- Returns synthesized answer alongside deduplicated source URLs[cite: 1, 4].

## 11. Experimental Hypothesis

**Core claim**: indexing LLM-generated questions (dense) alongside chunk text (sparse) yields higher retrieval accuracy and better semantic alignment than chunk-only retrieval[cite: 1].

**Supported pipeline configurations**:
- Dense question retrieval + sparse chunk retrieval + RRF fusion[cite: 1, 7].
- Cross-encoder reranking over RRF fused candidates[cite: 7, 8].
- Structure-aware chunking with SQL-based small-to-big context expansion[cite: 3, 7].

**Methodological gap**:
- Dense representations are currently computed exclusively for generated questions; chunks lack a separate dense vector[cite: 1, 3]. Baseline comparisons of chunk-only vs question-augmented dense retrieval require generating dense vectors directly on chunk bodies[cite: 1].

## 12. Status Matrix & Implementation Audit

| Capability | Status |
|---|---|
| Discovery, scrape, chunk, qgen, embed, Qdrant sync | **[IMPLEMENTED]**[cite: 1] |
| Tenant payload partitioning + is_tenant HNSW | **[IMPLEMENTED]**[cite: 1, 10] |
| Dense + sparse hybrid retrieval + custom chunk-level RRF | **[IMPLEMENTED]**[cite: 1, 7] |
| Structure-aware markdown chunker (`chunker.py`) | **[IMPLEMENTED]**[cite: 3] |
| Cross-encoder reranker (`FastEmbed`, `FlashRank`, `Transformers`) | **[IMPLEMENTED]**[cite: 7, 8] |
| Context expander (SQL small-to-big window and section stitching) | **[IMPLEMENTED]**[cite: 7] |
| Campus-aware payload indexing and query filtering | **[IMPLEMENTED]**[cite: 7, 10] |
| Redis semantic cache (tenant- and campus-scoped) | **[IMPLEMENTED]**[cite: 7, 9] |
| Structured intent classification + ambiguous query note | **[IMPLEMENTED]**[cite: 7] |
| Out-of-scope query gating via reranker threshold | **[IMPLEMENTED]**[cite: 6, 7, 8] |
| Scope verification / LLM-based query gatekeeper | [PLANNED][cite: 1] |
| Automated recurring scrape scheduler (`website_scrape_schedules`) | [PLANNED][cite: 1, 6] |
| Qdrant point cleanup on page/website re-scrape or deletion | [IMPLEMENTED][cite: 1] |
| Role-based authorization (`admin` vs `member` access checks) | [PLANNED][cite: 1, 6] |
| Dense chunk embedding baseline for ablation | [PLANNED][cite: 1] |

## 13. Conventions for Agents Editing This Repo

- Never issue a Qdrant or cache call without the tenant identifier (`org_id` / `group_id`)[cite: 1].
- New providers must implement the abstract base class and register in the corresponding factory[cite: 1].
- Pipeline stages must be idempotent and checkpointed in PostgreSQL[cite: 1]. Failures must never mark work as completed[cite: 1].
- Maintain thesis-relevant telemetry (`MatchedQuestionDetail`, initial scores, rerank scores, method telemetry) across pipelines[cite: 1, 4, 7, 8].
- When changing pipeline logic, configuration parameters, or data models, update this file in the same change[cite: 1].