# RAG System Architecture & Agent Context

## System Overview

This is a **multi-tenant Retrieval-Augmented Generation (RAG)** system designed to enable universities and organizations to build semantic search capabilities over their website content. The core innovation is **question-augmented indexing**: instead of storing only chunks, we generate 3-5 semantically-relevant questions per chunk and index those questions as dense vectors, leveraging the hypothesis that questions are closer to user intent than raw text chunks in semantic space.

**Thesis Validation**: This system tests whether question-augmented dense vectors improve retrieval accuracy compared to chunk-only retrieval.

---

## Data Architecture

### Single Qdrant Point Structure

Each vector point in Qdrant represents a content chunk with the following structure:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        QDRANT VECTOR POINT                             │
├────────────────────────────────────────────────────────────────────────┤
│ ID: UUID (parent chunk identifier)                                      │
│ SHARD_KEY: "mit" | "stanford" | etc. (tenant isolation via payload)    │
├────────────────────────────────────────────────────────────────────────┤
│ DENSE VECTORS (HNSW Index):                                            │
│   - question_vector_1: [0.12, -0.43, 0.67, ...]                        │
│   - question_vector_2: [0.05,  0.88, -0.21, ...]                       │
│   - question_vector_3: [0.91, -0.11,  0.34, ...]                       │
│   (Up to 5 questions per chunk)                                         │
├────────────────────────────────────────────────────────────────────────┤
│ SPARSE VECTOR:                                                          │
│   - chunk_sparse: {indices: [0, 5, 12, ...], values: [0.8, 0.4, ...]}  │
│     (BM25-style term frequency encoding of chunk text)                  │
├────────────────────────────────────────────────────────────────────────┤
│ PAYLOAD (Metadata):                                                     │
│   - chunk_text: "The actual plaintext content of this chunk..."         │
│   - source_url: "https://example.com/page"                              │
│   - tenant_id: "mit" (used for shard key filtering)                     │
└────────────────────────────────────────────────────────────────────────┘
```

### Multi-Tenancy Strategy

- **Single Master Collection**: All tenants reside within a single collection and shard, avoiding the memory, index, and segment overhead of multi-collection or cluster-sharded architectures.
- **Payload-Based Partitioning (group_id)**: Every point contains a tenant identifier in its payload metadata (e.g., group_id: "mit" or group_id: "stanford").
- **Tenant-Aware HNSW Sub-Indexing (is_tenant=true)**: The group_id payload field is configured with is_tenant=true. This compels Qdrant to construct isolated, tenant-specific graph edge structures within segments, preventing HNSW graph pollution, eliminating cross-tenant search dead ends, and preserving search recall.
- **Strict Query-Time Filtering**: Every incoming query applies a mandatory group_id match filter as a hard constraint, mathematically guaranteeing zero cross-tenant data leakage or vector bleeding.

---

## Ingestion Pipeline

**Purpose**: Transform raw website content into indexed, searchable vectors.

### Flow

```
[1. Website Scraping]
         ↓
    Extract raw HTML/text from target domains
         ↓
[2. Chunking]
         ↓
    Split content into semantically coherent chunks
    (handles overlap and tokenization)
         ↓
[3. Question Generation]
         ↓
    LLM generates 3-5 questions per chunk that
    capture intent and key concepts
         ↓
[4. Vector Encoding]
         ↓
    Parallel encoding:
    • Dense: Embed each question (DENSE VECTORS)
    • Sparse: BM25 tokenization of chunk text (SPARSE VECTOR)
         ↓
[5. Database Persistence]
         ↓
    Store single Qdrant point with:
    - Multiple question embeddings
    - One sparse vector for the chunk
    - Full plaintext chunk in payload
    - Tenant shard key
```

### Fault Tolerance

The pipeline includes retry mechanisms for cases where:
- Scraping fails mid-process
- LLM generation times out
- Database writes are interrupted

These cases are logged with recovery checkpoints to allow resumption.

---

## Query Flow (Runtime)

**Purpose**: Execute user queries against the indexed corpus with intelligent routing and fallback.

### Flow

```
[User Query Input]
         ↓
[1. Query Embedding]
         ↓
    Convert query to dense vector using same
    encoder as training questions
         ↓
[2. Semantic Cache Lookup]
         ↓
    ┌─ Cache hit (>85% cosine similarity)?
    │       ↓ YES
    │  [Return Cached Answer] ← Fast path
    │
    └─ Cache miss (<85% similarity)?
            ↓ NO
         Continue to retrieval
            ↓
[3. Scope Verification]
         ↓
    Is query within database scope?
    (e.g., asking about MIT-specific content
     when querying MIT tenant)
         ↓
    ├─ YES → Continue to retrieval
    │
    └─ NO → [Send Fallback Response]
            ("Not in knowledge base")
            ↓
[4. Database Retrieval Check]
         ↓
    Query Qdrant with dense vector:
    • Retrieve top-k matching question vectors
    • Filter by shard key (tenant isolation)
    • Hybrid retrieval if sparse vector enabled
         ↓
    ├─ Found relevant chunks?
    │       ↓ YES
    │  [Retrieved Chunks with Scores]
    │       ↓
    │  [5. Context Assembly & LLM Call]
    │       ↓
    │  Pack retrieved chunks into prompt
    │  with retrieved metadata (URLs, etc.)
    │       ↓
    │  [Send Context + Query to LLM]
    │       ↓
    │  [Generate Response]
    │       ↓
    │  [6. Cache Generated Response]
    │       ↓
    │  Store Q&A pair with query embedding
    │  and response for future cache hits
    │       ↓
    │  [Return Generated Response]
    │
    └─ No relevant chunks?
            ↓ NO
        [Send Fallback Response]
        (indicates retrieval failure)
            ↓
        [Optionally Cache Fallback]
```

### Key Decision Points

| Condition | Action |
|-----------|--------|
| Cache hit (similarity > 85%) | Return cached answer immediately |
| Out of scope | Return fallback without retrieval |
| Not in database | Return fallback + log miss |
| Retrieval success | Generate + cache + return |

---

## Retrieval Strategy (Hybrid Approach)

### Dense Retrieval Path

```
[Query Vector Embedding]
         ↓
    HNSW Index Search
    (hierarchical navigable small world)
         ↓
    [Retrieve Top-K Questions by Cosine Distance]
         ↓
    [Return Associated Chunks from Payload]
```

**Why Dense for Questions**: 
- Semantic similarity in embedding space aligns with user intent
- Questions capture *intent* better than raw chunks
- Hypothesis being tested in thesis

### Sparse Retrieval Path

```
[Query Term Extraction]
         ↓
    BM25 Tokenization
         ↓
    [Sparse Vector Matching Against Chunk Vectors]
         ↓
    [Retrieve Top-K by TF-IDF Scores]
         ↓
    [Return Associated Chunks]
```

**Why Sparse for Chunks**:
- Exact term matching for keyword-heavy queries
- Essential complement to dense retrieval when query uses specialized terminology
- Hybrid scoring: combine dense + sparse scores for final ranking
- **Mandatory for all queries** to ensure coverage of both semantic and lexical matching

### Hybrid RRF (Reciprocal Rank Fusion)

```
[Dense Retrieval Results]        [Sparse Retrieval Results]
         ↓                                  ↓
         └──→ [RRF Reranker] ←─────────────┘
                    ↓
           [Cross-Encoder Reranker]
           (optional LLM-based ranking)
                    ↓
              [Final Ranked List]
                    ↓
              [LLM Generation]
```

The system combines dense and sparse results using Reciprocal Rank Fusion for balanced coverage.

---

## Experimental Hypothesis

**Core Claim**: Indexing LLM-generated questions (dense vectors) alongside chunks (sparse vectors) yields higher retrieval accuracy and better semantic alignment with user queries compared to chunk-only retrieval.

**What We're Measuring**:
- Retrieval precision@k (are top-k results relevant?)
- Cosine similarity distribution (do questions cluster closer to intent?)
- Query-to-chunk similarity magnitude vs. query-to-question similarity magnitude
- End-to-end answer quality (perplexity, ROUGE, human eval)

**Validation**: This architecture allows controlled ablations:
- Dense-only (question vectors only)
- Sparse-only (chunk vectors only)
- Hybrid (both, with RRF)

---

## Tenant Isolation & Security

- **Shard Key**: Every query must specify tenant (e.g., `shard_key: "mit"`)
- **Query Filtering**: Qdrant filter ensures zero cross-tenant data leakage
- **Metadata Payload**: Tenant ID stored redundantly in chunk_text metadata URL context
- **No Cross-Tenant Indexing**: LLM generation is per-tenant to prevent knowledge transfer
