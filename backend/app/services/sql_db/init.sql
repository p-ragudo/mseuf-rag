-- Enable pgcrypto for UUID validation if needed
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS scraped_pages (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    source_url TEXT NOT NULL,
    raw_markdown TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'SCRAPED',
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_scraped_pages_tenant_url UNIQUE (tenant_id, source_url)
);

CREATE INDEX IF NOT EXISTS idx_scraped_pages_tenant_status 
ON scraped_pages (tenant_id, status);


CREATE TABLE IF NOT EXISTS document_chunks (
    id VARCHAR(36) PRIMARY KEY,
    scraped_page_id VARCHAR(36) NOT NULL REFERENCES scraped_pages(id) ON DELETE CASCADE,
    tenant_id VARCHAR(64) NOT NULL,
    source_url TEXT NOT NULL,
    title VARCHAR(255) NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING_QGEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_document_chunks_page_index UNIQUE (scraped_page_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_tenant_status 
ON document_chunks (tenant_id, status);