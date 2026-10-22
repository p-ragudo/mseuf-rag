# RAG System Architecture & Agent Context

> Last audited against the backend code: 2026-10-22.
> Status tags: **[IMPLEMENTED]** matches the code, **[PARTIAL]** exists but incomplete or flawed, **[PLANNED]** designed but not built.
> Where this file and the code disagree, the code wins. Fix the code or update this file in the same change.

## 1. System Overview

A **multi-tenant Retrieval-Augmented Generation (RAG) service**. Organizations (tenants) register websites for automated recursive crawling or upload documents directly (`.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`) under a virtual `document://` scheme. The system cleans, chunks, generates synthetic questions, and indexes content in Qdrant for semantic question answering isolated strictly to each organization's data.

The core retrieval architecture uses **question-augmented indexing**:
- For every markdown chunk, an LLM generates 3–5 grounded synthetic questions.
- Each generated question becomes its own Qdrant point carrying a **dense vector of the synthetic question** (`question_dense`).
- Each question point also carries a **BM25 sparse vector of the parent chunk text** (`chunk_sparse`).
- Query runtime enforces **conversation turn history resolution**, **regex-based PII redaction**, **query intent classification & rewrite**, **semantic caching**, **reciprocal rank fusion (RRF)**, **cross-encoder reranking**, **temporal conflict resolution (supersession)**, and **SQL small-to-big context expansion** before grounded LLM answer synthesis.

## 2. Tech Stack

| Concern | Choice |
|---|---|
| API | FastAPI, async everywhere |
| Relational store | PostgreSQL via SQLAlchemy 2.x async (source of truth for tenants, pages, chunks, questions, sessions, responses, branding, schedules) |
| Vector DB | Qdrant (`AsyncQdrantClient`, single collection resolved via `settings.resolved_collection_name`) |
| Dense embeddings | Gemini embeddings (`models/text-embedding-004` or configured model) via `EmbedderFactory` (with FastEmbed, SentenceTransformers, and Ollama alternatives; default 768 / 3072 dim) |
| Sparse embeddings | fastembed `Qdrant/bm25` (`FastEmbedSparseEmbedder`), IDF modifier applied server-side by Qdrant |
| Cross-encoder reranker | fastembed `TextCrossEncoder` (default `Xenova/ms-marco-MiniLM-L-12-v2`), with FlashRank and PyTorch Transformers alternatives |
| Question generation | Gemini (`gemini-2.5-flash`), temperature 0.2, batches of 10 chunks per structured JSON call |
| Answer synthesis | Gemini (``), temperature 0.3, max 2048 output tokens |
| Intent classifier | Gemini (`gemini-3.5-flash-lite`), structured JSON output via Pydantic schema (`QueryIntent`) with conversational follow-up rewriting |
| Semantic cache | Redis via RedisVL `SemanticCache` (or in-memory mock), tenant- and campus-scoped with `content_version` invalidation |
| Web Scraping | crawl4ai `AsyncWebCrawler`, httpx, recursive sitemaps and robots.txt discovery with crawl trap detection |
| Document Ingestion | pypdf (PDF), python-docx (DOCX), antiword CLI (DOC), openpyxl (XLSX), xlrd (XLS) |
| Chunking | Structure-aware markdown chunker (`chunker.py` using heading hierarchy, atomic blocks, and section packing) |
| Conversation Memory | `SessionMessage` table with rolling window (last 6 messages / 3 turns) and 24-hour TTL pruning |
| Privacy | Local regex PII redaction (email, phone, payment cards with Luhn check, government IDs, addresses, labeled names) |
| Auth & RBAC | JWT (HS256, python-jose), bcrypt via pwdlib; role-based access checks (`admin`, `ingester`, `designer`, `member`) via `require_org_role` |
| Ops & Admin | Telegram long-poll bot (`/scrape`, `/status`, `/help`) |

All external vector, embedding, LLM, cache, and reranker providers sit behind abstract bases and factories (`get_vector_db`, `get_embedder`, `get_sparse_embedder`, `get_reranker`, `get_question_generator`, `get_qa_synthesizer`, `get_semantic_cache`).

## 3. Repository Layout

```text
backend/
  app/
    core/        config.py, database.py, security.py
    models/      chunk.py, generated_question.py, org.py, org_branding.py,
                 org_member.py, response.py, scraped_page.py,
                 session_message.py, user.py, website.py, website_schedule.py
    routes/      auth.py, branding.py, ingest.py, orgs.py, query.py, stats.py, websites.py
    schemas/     tenant.py
    services/
      embeddings/        base.py, factory.py, gemini_embedder.py, sparse_embedder.py,
                         fastembed_embedder.py, sentence_transformer_embedder.py,
                         ollama_embedder.py, schema.py
      ingest_pipeline/   chunk.py, chunker.py, clean_markdown.py, discovery.py,
                         document_parser.py, orchestrator.py, scraper.py, schema.py
      llm_qa/            base_qa.py, factory.py, gemini_provider.py, schema.py,
                         sys_instructions.py
      llm_qgen/          base_qgen.py, factory.py, gemini_provider.py, openai_provider.py,
                         schema.py, sys_instructions.py
      query_pipeline/    context_expander.py, intent_classifier.py, pii_filter.py,
                         query_pipeline.py, schema.py, session_context.py,
                         temporal_resolver.py
      reranker/          base.py, factory.py, fastembed_provider.py,
                         flashrank_provider.py, transformers_provider.py, schema.py
      semantic_cache/    base.py, factory.py, in_memory_cache.py, redis_cache.py,
                         schemas.py
      vector_db/         base.py, factory.py, qdrant_provider.py, schema.py
    utils/       org_roles.py, telegram_bot.py, temporal.py, uuid_generator.py
    main.py
    qdrant_duplicate_collection.py
  scripts/
  tests/
```

## 4. Relational Data Model (PostgreSQL)

```text
users 1──* org_members *──1 orgs 1──* websites 1──1 website_scrape_schedules
                             │   websites 1──* scraped_pages 1──* chunks 1──* generated_questions
                             ├───1 org_branding, org_chat_settings, org_chat_headers, org_chat_fonts
                             ├───* responses
                             └───* session_messages
```

| Table | Key Fields | Notes |
|---|---|---|
| `users` | `id`, `email`, `password_hash`, `first_name`, `last_name` | Registered user credentials and identity. |
| `orgs` | `id`, `creator_id`, `name`, `content_version` | `content_version` increments on new chunking/sync/delete to invalidate semantic cache scopes. |
| `org_members` | `(user_id, org_id)` PK, `roles` (`admin`, `ingester`, `designer`, `member`) | Endpoint-level RBAC is strictly enforced via `require_org_role` utility. |
| `org_branding` | `org_id` PK, `color`, `mascot_png` (deferred bytes), `mascot_updated_at`, `updated_at` | White-label branding per tenant. |
| `org_chat_settings` | `org_id` PK, `assistant_name` | Configurable assistant identity (default: "Chat Assistant"). |
| `org_chat_headers` | `org_id` PK, `header_tagline` | Configurable chat banner tagline. |
| `org_chat_fonts` | `org_id` PK, `font_family` | Supported font families (`system`, `arial`, `georgia`, `verdana`, `trebuchet`, `courier`). |
| `websites` | `id`, `org_id`, `url`, `status` (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`), `error_message` | Represents either a web domain or a virtual uploaded document bundle (`document://{uuid}`). |
| `website_scrape_schedules` | `id`, `web_id` (unique FK), `interval_days`, `time_of_scrape`, `last_scraped_at`, `next_scraped_at` | Scrape schedule records; background cron daemon remains **[PLANNED]**. |
| `scraped_pages` | `id`, `org_id`, `web_id`, `url`, `markdown_content`, `status`, `retries`, `content_hash`, `doc_period`, `content_changed_at`, `last_scraped_at`, `last_seen_at`, `qdrant_cleanup_pending`, `chunked_at` | Unique on `(org_id, web_id, url)`. Stores web pages or parsed document files (`document://{uuid}/{filename}`). |
| `chunks` | `id`, `page_id`, `content`, `token_count`, `has_qgen`, `chunk_index`, `section_id`, `heading_path`, `part_index`, `part_total`, `qgen_attempts`, `chunk_hash` | Indexes on `(has_qgen, qgen_attempts)` and `(page_id, chunk_index)`. |
| `generated_questions` | `id`, `chunk_id`, `question`, `is_synced_qdrant`, `is_synced_gemini`, `is_synced_gemini_768`, `is_synced_bge_m3` | Per-model sync flags track indexing across multi-model benchmark runs. |
| `session_messages` | `id`, `org_id`, `session_id`, `role`, `content`, `created_at` | Ephemeral chat history. Filtered by 24h TTL and pruned opportunistically. |
| `responses` | `id`, `org_id`, `satisfied`, `latency_ms`, `accessed_chunks`, `accessed_generated_questions`, `created_at` | Operational analytics and feedback telemetry. |

## 5. Qdrant Data Model

### Point Structure (One point per generated question) [IMPLEMENTED]

```text
┌────────────────────────────────────────────────────────────────────────┐
│ ID: UUIDv5 = f(chunk_id, question_text)                                │
├────────────────────────────────────────────────────────────────────────┤
│ DENSE (named: question_dense)   embedding of the QUESTION              │
│   size=embedder.dimension, Cosine distance, on_disk=true,              │
│   HNSW m=0, payload_m=16, scalar (int8) / binary quantization          │
├────────────────────────────────────────────────────────────────────────┤
│ SPARSE (named: chunk_sparse)    fastembed BM25 of the PARENT CHUNK     │
│   in-RAM index, Modifier.IDF (repeated for each question of that chunk)│
├────────────────────────────────────────────────────────────────────────┤
│ PAYLOAD                                                                │
│   group_id         str(org_id) (keyword indexed, is_tenant=True)       │
│   campus           sub-entity slug from URL (keyword indexed)          │
│   page_id          integer indexed                                     │
│   chunk_id         integer indexed                                     │
│   web_id           Postgres website PK                                 │
│   parent_chunk_id  UUIDv5 of the chunk                                 │
│   question_text    the synthetic question text                         │
│   chunk_text       full parent chunk content                           │
│   source_url       page or document URL                                │
│   chunk_index      0-based page reading order                          │
│   section_id       stable section hash                                 │
│   heading_path     heading hierarchy breadcrumb                        │
│   part_index       1-based part index                                  │
│   part_total       total parts in section                              │
│   doc_type         "ephemeral" | "evergreen"                           │
│   academic_level   "shs" | "basic_ed" | "undergraduate" | "graduate"  │
│   doc_period       starting academic year integer (e.g. 2025)          │
│   page_updated_at  ISO timestamp of content change                     │
└────────────────────────────────────────────────────────────────────────┘
```

### Collection & Indexing Configuration

- **Collection Name**: dynamically resolved via `settings.resolved_collection_name`.
- **Payload Partitioning**: keyword index on `group_id` with `is_tenant=True`.
- **Sub-entity Filtering**: keyword index on `campus`.
- **Reconciliation Indices**: integer payload indices on `page_id` and `chunk_id`.
- **HNSW Topology**: `m=0` (disables global cross-tenant graph edges) and `payload_m=16` (builds edges strictly within tenant/filter boundaries).
- **Quantization**: supports scalar (int8, quantile 0.99) or binary quantization with `always_ram=True`. Query execution rescores with `oversampling=2.0`.

### Deterministic UUID Scheme (`utils/uuid_generator.py`)

Deterministic UUIDv5 inside namespace `a3bb189e-8bf9-4888-9912-ace4e6543002`:
- `doc_id = f("doc::{tenant_id}::{source_url}")`
- `chunk_id = f("chunk::{tenant_id}::{source_url}#{chunk_index}:{content}")`
- `question_id = f("question::{chunk_id}:{question}")`
- `sparse_id = f("sparse::{model_name}:{parent_id}")`

## 6. Multi-Tenancy & Security Model

**Implemented**:
- **Strict Query Scoping**: all vector and sparse searches pass `{"group_id": str(org_id)}`.
- **Tenant HNSW Graphs**: Qdrant tenant routing via `is_tenant=True` avoids cross-tenant vector interference.
- **Cache Scoping & Version Invalidation**: semantic cache keys incorporate tenant ID, detected campus, and `Org.content_version` (`{org_id}_v{version}[_{campus}]`).
- **SQL RBAC Authorization**: mutating routes check role requirements via `require_org_role`:
  - `CONTENT_MANAGER_ROLES = ("admin", "ingester")` for websites, document uploads, and scrape triggers.
  - `BRANDING_MANAGER_ROLES = ("admin", "designer")` for mascot, color, and chat styling.
  - Organization admins can invite members, update roles, transfer adminship, and remove non-owner members.
- **Relational Integrity**: Small-to-big context expansion enforces `ScrapedPage.org_id == org_id` directly in SQL.
- **Cascade Vector Deletions**: Deleting a website or uploaded document executes `delete_points` in Qdrant filtered by `group_id` and `web_id` prior to database deletion.
- **Reconciliation & Purge**: Re-chunked pages sweep obsolete points via `reconcile_stale_points`. Dropped pages trigger `purge_missing_pages`.

## 7. Ingestion Pipeline

Ingestion handles two distinct sources:
1. **Web Scrapes**: triggered via `POST /ingest/run/{website_id}` or Telegram `/scrape <id>`.
2. **Document Uploads**: triggered via `POST /ingest/documents` and `PUT /ingest/documents/{document_id}` for `.pdf`, `.docx`, `.doc`, `.xlsx`, and `.xls` files.

### 7.1 Web Ingestion Architecture

Five concurrent asynchronous stages in `orchestrator.py` coordinated by `asyncio.Event` flags:

```text
 discovery ──▶ scraper ──▶ chunker ──▶ qgen ──▶ qdrant_sync
```

1. **Discovery Stage** (`discovery.py`):
   - Crawls `robots.txt` and candidate sitemaps (`sitemap.xml`, `sitemap_index.xml`, `wp-sitemap.xml`).
   - Falls back to 1-level internal link crawl via crawl4ai if sitemaps are missing.
   - Detects crawl traps (calendar loops, query recursion, binary files).
   - Inserts or updates `scraped_pages` records in batches of 200, setting `last_seen_at`.
2. **Scraper Stage** (`orchestrator.py`):
   - Worker fetches pending pages in batches of 10 using `crawl4ai.AsyncWebCrawler`.
   - Strips non-content tags (`nav`, `footer`, `header`, `script`, `style`, `noscript`, `aside`, `form`).
   - Normalizes text and computes SHA256 hashes (`_hash_markdown`). Unchanged hashes skip re-chunking.
   - Retries up to 3 times before setting status to `FAILED`. If an existing page fails refresh, its previous valid content is preserved.
3. **Chunking Stage** (`chunk.py`, `chunker.py`, `clean_markdown.py`):
   - Strips YAML frontmatter, cleans HTML tags, normalizes whitespace and markdown artifacts.
   - Structure-aware chunking parses sections according to heading depth, attaches breadcrumbs, preserves code fences, tables, and lists as atomic blocks, packs small sibling sections, and handles oversized text splits with `(part i of n)` labels.
   - Replaces existing page chunks inside an atomic transaction, marking `qdrant_cleanup_pending=True` if old chunks existed.
   - Extracts academic cycle year (`doc_period`) via `temporal.py`.
4. **Question Generation Stage** (`orchestrator.py`, `services/llm_qgen/`):
   - Chunks are fetched in batches of 10.
   - Gemini (``, temperature 0.2) generates 3–5 grounded synthetic questions per chunk using structured JSON output.
   - Successful generations insert `GeneratedQuestion` records and set `has_qgen=True`.
   - Failed or unreturned chunks increment `qgen_attempts` (capped at 3).
5. **Qdrant Sync Stage** (`orchestrator.py`):
   - Fetches pending questions in batches of 100.
   - Dense embeddings generated for question text with `task_type="RETRIEVAL_DOCUMENT"`.
   - Sparse BM25 embeddings generated for parent chunk text.
   - Upserts points with complete metadata payloads into Qdrant (`wait=True`).
   - Updates `GeneratedQuestion.is_synced_qdrant` and the active model sync column.
6. **Reconciliation, Purge & Cache Invalidation**:
   - `reconcile_stale_points`: sweeps points in Qdrant for pages with `qdrant_cleanup_pending=True` where `chunk_id` is no longer in SQL.
   - `purge_missing_pages`: drops pages and Qdrant points no longer discovered during crawl, bounded by a 50% safety guard.
   - Increments `Org.content_version`, invalidating previous semantic cache keys.

### 7.2 Uploaded Document Pipeline (`ingest_uploaded_document`)

- Uploaded files are parsed via `document_parser.py`:
  - `.pdf`: `pypdf.PdfReader` with max 2,000 pages and 1,000,000 characters limit.
  - `.docx`: `docx.Document` with zip-bomb protection (max 5,000 zip entries, max 100MB uncompressed).
  - `.doc`: Legacy MS Word extracted via local `antiword` binary.
  - `.xlsx` / `.xls`: `openpyxl` / `xlrd` tabular extraction with pipe-delimited row formatting.
- Stored under synthetic website URL `document://{uuid}` and page URL `document://{uuid}/{filename}`.
- Formats markdown with `# {filename}\n\nCategory: {category}\n\n{extracted_text}`.
- Runs atomic chunking, synchronous batch QGen verification, and vector synchronization.
- Rolls back and clears partial vectors if any chunk fails question generation or synchronization.

## 8. Query Pipeline (Runtime)

Handled by `POST /query/{org_id}` via `QueryPipeline.execute`:

```text
[User Query + Session ID]
   ↓
[1. Conversation History & PII Sanitization]
   ├─ Load last 6 unexpired session messages (24h TTL) from PostgreSQL
   ├─ Redact PII (email, phone, payment cards, IDs, addresses, names) in query & history
   ├─ Check Org readiness (has_indexed_content)
   └─ Housekeeping: background purge of expired session messages
   ↓
[2. Intent Classification & Follow-Up Resolution]
   ├─ If history exists: QueryClassifier (Gemini 3.5 Flash Lite) detects if follow-up
   │    ├─ Follow-up rewritten -> standalone query used for retrieval & cache
   │    └─ Follow-up fallback -> query concatenation used, cache bypassed
   └─ Parallel: embed search query (dense RETRIEVAL_QUERY + sparse BM25)
   ↓
[3. Multi-Tier Semantic Cache Check]
   ├─ Check base cache scope: "{org_id}_v{version}"
   ├─ Check sub-entity cache scope: "{org_id}_v{version}_{campus}"
   └─ HIT → Return cached answer & contexts (source="cache")
   ↓ MISS
[4. Hybrid Retrieval in Qdrant]
   ├─ Parallel query_points: question_dense ∥ chunk_sparse
   ├─ Filter: group_id (mandatory) + campus (if detected)
   └─ Fallback: retry tenant-wide if campus search yields 0 hits
   ↓
[5. Chunk-Level Reciprocal Rank Fusion (RRF)]
   ├─ k=60; dense hit scores accumulate across matching questions
   ├─ Sparse parent chunk hit score added once
   └─ If empty → Return fallback response (source="fallback")
   ↓
[6. Cross-Encoder Reranker]
   ├─ Candidate pool: max(top_k * 4, 25)
   ├─ Over-fetches (top_k * 2) candidates via FastEmbed / FlashRank / Transformers
   └─ Reranker score threshold gating filters out irrelevant queries
   ↓
[7. Temporal Conflict Resolution]
   ├─ Clusters candidate chunks by heading, URL stem, and token Jaccard similarity
   ├─ Prunes older academic periods or stale update timestamps in favour of fresher versions
   └─ Retains top_k reranked results; logs superseded documents
   ↓
[8. Small-to-Big Context Expansion]
   ├─ Reloads matching sections by section_id and +/- 1 window neighbours from PostgreSQL
   ├─ Merges contiguous page chunks in reading order
   └─ Enforces SQL tenant isolation (ScrapedPage.org_id == org_id) and character budget (16k chars)
   ↓
[9. Grounded Answer Synthesis]
   ├─ Gemini 2.5 Flash, temperature 0.3
   ├─ Contexts wrapped in XML-delimited untrusted <document> tags with branch & period metadata
   ├─ System instructions enforce strict grounding, branch distinction, and recency preference
   └─ Clarification note appended if intent was flagged ambiguous
   ↓
[10. Cache Storage & Interaction Logging]
   ├─ Store final synthesized response in RedisVL semantic cache
   ├─ Save sanitized user & assistant turns to session_messages
   └─ Log response latency, accessed chunks, and accessed questions to responses table
   ↓
[Return PipelineQueryResponse: answer, is_cached, source, sources, contexts, superseded, response_id]
```

## 9. Retrieval, Reranking & Freshness Strategy

### Hybrid Fusion (RRF)
Reciprocal Rank Fusion aggregates question points back into unique parent chunks:
$$RRF\_Score(chunk) = \sum_{q \in DenseHits(chunk)} \frac{1}{60 + rank(q) + 1} + \frac{1}{60 + rank(chunk_{sparse}) + 1}$$
Dense question hits accumulate, prioritizing chunks answering the query from multiple angles.

### Cross-Encoder Gating
Fused candidates pass to a cross-encoder (`fastembed` ONNX `Xenova/ms-marco-MiniLM-L-12-v2` by default). Candidates below `settings.reranker_score_threshold` are pruned to gate out irrelevant queries before LLM invocation.

### Temporal Conflict Resolution (`temporal_resolver.py`)
- Candidate chunks are clustered based on token Jaccard overlap ($\ge 0.75$), matching normalized headings ($\ge 0.40$), or matching URL stems ($\ge 0.45$).
- When documents within a cluster conflict:
  - If the user specifies an explicit year or academic period (e.g. `2024`), conflicting periods are dropped.
  - Otherwise, candidate chunks with newer academic years (`doc_period`) or update timestamps older by $> 1$ day are suppressed.
- Suppressed documents are logged and surfaced in telemetry as `superseded`.

### Context Expansion (`context_expander.py`)
Rather than passing fragmented chunks to the LLM:
- Queries PostgreSQL for all sibling chunks sharing the same `section_id`.
- Fetches adjacent chunks within a $\pm 1$ index window for top-ranked hits.
- Merges contiguous chunks into a unified document in reading order up to 16,000 characters.

## 10. Status Matrix & Implementation Audit

| Capability | Status | Implementation Details |
|---|---|---|
| Automated discovery, scrape, chunk, qgen, embed, sync | **[IMPLEMENTED]** | 5-stage async pipeline in `orchestrator.py`. |
| Direct Document Ingestion (.pdf, .docx, .doc, .xlsx, .xls) | **[IMPLEMENTED]** | Multi-format extraction via `document_parser.py` and dedicated upload endpoints in `routes/ingest.py`. |
| Structure-aware markdown chunking | **[IMPLEMENTED]** | `chunker.py` and `clean_markdown.py`. |
| Question-augmented dense + chunk sparse indexing | **[IMPLEMENTED]** | `question_dense` + `chunk_sparse` in Qdrant. |
| Multi-tenant HNSW payload partitioning | **[IMPLEMENTED]** | `is_tenant=True` on `group_id`, `m=0`, `payload_m=16`. |
| Multi-model embedding checkpoints | **[IMPLEMENTED]** | `is_synced_gemini_768`, `is_synced_gemini`, `is_synced_bge_m3`. |
| Sub-entity / Campus classification & filtering | **[IMPLEMENTED]** | `QueryClassifier` + Qdrant `campus` index with fallback. |
| Hybrid retrieval with chunk-accumulating RRF | **[IMPLEMENTED]** | `_reciprocal_rank_fusion` in `QueryPipeline`. |
| Cross-encoder reranking | **[IMPLEMENTED]** | FastEmbed, FlashRank, and PyTorch Transformers providers. |
| Query gating via reranker threshold | **[IMPLEMENTED]** | Configured via `settings.reranker_score_threshold`. |
| Temporal conflict resolution & document supersession | **[IMPLEMENTED]** | `temporal_resolver.py` pruning stale academic periods. |
| SQL small-to-big context expansion | **[IMPLEMENTED]** | `context_expander.py` section and window stitching. |
| Multi-turn conversation memory | **[IMPLEMENTED]** | PostgreSQL `SessionMessage` table, 24h rolling TTL, standalone rewrite. |
| Client-side privacy redaction | **[IMPLEMENTED]** | Local regex filter in `pii_filter.py` with Luhn validation. |
| Multi-role RBAC enforcement | **[IMPLEMENTED]** | `require_org_role` checking `admin`, `ingester`, `designer`, `member`. |
| White-label tenant branding & chat styling | **[IMPLEMENTED]** | `routes/branding.py` managing mascots, colors, taglines, and fonts. |
| Usage analytics & satisfaction tracking | **[IMPLEMENTED]** | `routes/stats.py` tracking inquiry volume, satisfaction rate, and top chunks. |
| Semantic caching with version-scoped invalidation | **[IMPLEMENTED]** | RedisVL / in-memory cache keyed with `content_version`. |
| Stale vector reconciliation and page purge | **[IMPLEMENTED]** | `reconcile_stale_points` and `purge_missing_pages`. |
| Telegram operational poller | **[IMPLEMENTED]** | `/scrape` and `/status` bot commands running alongside FastAPI lifespan. |
| Scrape schedule cron runner | [PLANNED] | `website_scrape_schedules` table exists without scheduler daemon. |
| Dense chunk embedding baseline for ablation | [PLANNED] | Dense vectors currently created only for generated questions. |

## 11. Conventions for Working in This Codebase

- Always include the tenant scope (`group_id` / `org_id`) in Qdrant, PostgreSQL, and semantic cache operations.
- Providers must inherit from their service's abstract base class and register in the factory (`EmbedderFactory`, `RerankerFactory`, `get_vector_db`, etc.). Do not instantiate concrete provider classes directly in pipelines.
- Mutating endpoints affecting knowledge bases or tenant configurations must enforce permissions using `require_org_role` (`CONTENT_MANAGER_ROLES`, `BRANDING_MANAGER_ROLES`, or admin checks).
- Pipeline stages must remain idempotent and checkpoint progress in PostgreSQL. Never mark unverified stages as completed.
- Maintain telemetry attributes (`initial_score`, `rerank_score`, `matched_questions`, `superseded`) across pipeline transfers.
- Whenever updating schemas, pipeline flows, or configuration variables, update this file in the same commit.