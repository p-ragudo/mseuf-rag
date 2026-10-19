import asyncio
import io
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from docx import Document
from fastapi import BackgroundTasks, HTTPException, UploadFile

from app.models.scraped_page import PageProcessStatus, ScrapedPage
from app.models.website import Website, WebsiteScrapeStatus
from app.routes import ingest as ingest_route
from app.routes.ingest import (
    delete_document,
    get_document_ingestion_status,
    replace_document,
    upload_document,
)


class FakeMembershipResult:
    def scalar_one_or_none(self):
        return object()


class FakeDatabase:
    def __init__(self):
        self.records = []
        self.next_id = 1

    async def execute(self, _statement):
        return FakeMembershipResult()

    def add(self, record):
        self.records.append(record)

    async def flush(self):
        for record in self.records:
            if isinstance(record, Website) and record.id is None:
                record.id = self.next_id
                self.next_id += 1

    async def commit(self):
        for record in self.records:
            if isinstance(record, ScrapedPage) and record.id is None:
                record.id = self.next_id
                self.next_id += 1

    async def refresh(self, _record):
        return None


def test_document_upload_persists_extracted_text_and_schedules_indexing():
    source = Document()
    source.add_paragraph("Applicants submit a transcript to complete admission.")
    file_content = io.BytesIO()
    source.save(file_content)
    file = UploadFile(filename="admissions.docx", file=io.BytesIO(file_content.getvalue()))
    background_tasks = BackgroundTasks()
    db = FakeDatabase()

    result = asyncio.run(
        upload_document(
            background_tasks=background_tasks,
            org_id=7,
            category="Admissions Requirements",
            file=file,
            current_user=SimpleNamespace(id=3),
            db=db,
        )
    )

    website = next(record for record in db.records if isinstance(record, Website))
    page = next(record for record in db.records if isinstance(record, ScrapedPage))
    assert result["document_id"] == page.id
    assert result["status"] == "PENDING"
    assert website.org_id == 7
    assert website.url.startswith("document://")
    assert "Admissions Requirements" in page.markdown_content
    assert "Applicants submit a transcript" in page.markdown_content
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].kwargs == {"page_id": page.id}


class FakeStatusResult:
    def __init__(self, row=None, counts=(0, 0, 0), rows=()):
        self.row = row
        self.counts = counts
        self.rows = rows

    def one_or_none(self):
        return self.row

    def one(self):
        return self.counts

    def all(self):
        return self.rows


class FakeStatusDatabase:
    def __init__(self, counts):
        page = SimpleNamespace(
            id=51,
            url="document://doc-id/admissions%20guide.pdf",
            status=PageProcessStatus.COMPLETED,
        )
        website = SimpleNamespace(
            status=WebsiteScrapeStatus.COMPLETED,
            error_message=None,
        )
        self.results = [
            FakeStatusResult((page, website)),
            FakeStatusResult(counts=counts),
        ]

    async def execute(self, _statement):
        return self.results.pop(0)


def test_document_status_is_complete_only_after_every_question_is_synced():
    result = asyncio.run(
        get_document_ingestion_status(
            document_id=51,
            current_user=SimpleNamespace(id=3),
            db=FakeStatusDatabase(counts=(4, 12, 12)),
        )
    )

    assert result["status"] == PageProcessStatus.COMPLETED
    assert result["filename"] == "admissions guide.pdf"
    assert result["synced_questions"] == 12


def test_document_status_stays_in_progress_until_all_questions_are_synced():
    result = asyncio.run(
        get_document_ingestion_status(
            document_id=51,
            current_user=SimpleNamespace(id=3),
            db=FakeStatusDatabase(counts=(4, 12, 11)),
        )
    )

    assert result["status"] == PageProcessStatus.IN_PROGRESS


class FakeDocumentListDatabase:
    async def execute(self, _statement):
        if not hasattr(self, "query_count"):
            self.query_count = 0
        self.query_count += 1
        if self.query_count == 1:
            return FakeMembershipResult()
        if self.query_count == 2:
            page = SimpleNamespace(
                id=51,
                url="document://doc-id/admissions.pdf",
                markdown_content="Category: Admissions\n\nText",
                status=PageProcessStatus.COMPLETED,
            )
            website = SimpleNamespace(
                status=WebsiteScrapeStatus.COMPLETED,
                error_message=None,
            )
            return FakeStatusResult(rows=[(page, website)])
        return FakeStatusResult(rows=[(51, 3, 8, 8)])


def test_document_list_returns_member_documents_and_index_status():
    result = asyncio.run(
        ingest_route.list_documents(
            org_id=7,
            current_user=SimpleNamespace(id=3),
            db=FakeDocumentListDatabase(),
        )
    )

    assert result == [
        {
            "document_id": 51,
            "filename": "admissions.pdf",
            "category": "Admissions",
            "status": PageProcessStatus.COMPLETED,
            "error_message": None,
            "chunks": 3,
            "questions": 8,
            "synced_questions": 8,
        }
    ]


class FakeManagementDatabase:
    def __init__(self):
        self.page = SimpleNamespace(
            id=51,
            org_id=7,
            web_id=19,
            url="document://doc-id/old.pdf",
            markdown_content="# old document",
            content_hash="old-hash",
            status=PageProcessStatus.COMPLETED,
            chunked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            content_changed_at=None,
            last_scraped_at=None,
            qdrant_cleanup_pending=True,
        )
        self.website = SimpleNamespace(
            id=19,
            org_id=7,
            url="document://doc-id",
            status=WebsiteScrapeStatus.COMPLETED,
            error_message=None,
        )
        self.execute_calls = 0
        self.committed = False
        self.deleted = []

    async def execute(self, _statement):
        self.execute_calls += 1
        if self.execute_calls == 1:
            return FakeStatusResult((self.page, self.website))
        return FakeStatusResult()

    async def commit(self):
        self.committed = True

    async def delete(self, record):
        self.deleted.append(record)


def test_replace_document_clears_old_vectors_and_reschedules_ingestion(monkeypatch):
    source = Document()
    source.add_paragraph("The updated admissions deadline is September.")
    file_content = io.BytesIO()
    source.save(file_content)
    file = UploadFile(filename="updated.docx", file=io.BytesIO(file_content.getvalue()))
    background_tasks = BackgroundTasks()
    db = FakeManagementDatabase()
    deleted_vectors = []

    async def delete_vectors(org_id, web_id):
        deleted_vectors.append((org_id, web_id))

    monkeypatch.setattr(ingest_route, "_delete_document_vectors", delete_vectors)

    result = asyncio.run(
        replace_document(
            document_id=51,
            background_tasks=background_tasks,
            category="Admissions Requirements",
            file=file,
            current_user=SimpleNamespace(id=3),
            db=db,
        )
    )

    assert result["document_id"] == 51
    assert db.page.url.endswith("/updated.docx")
    assert "updated admissions deadline" in db.page.markdown_content
    assert db.page.chunked_at is None
    assert db.page.qdrant_cleanup_pending is False
    assert db.page.status == PageProcessStatus.PENDING
    assert db.website.status == WebsiteScrapeStatus.IN_PROGRESS
    assert deleted_vectors == [(7, 19)]
    assert len(background_tasks.tasks) == 1


def test_delete_document_removes_vectors_before_database_record(monkeypatch):
    db = FakeManagementDatabase()
    events = []

    async def delete_vectors(org_id, web_id):
        events.append(("vectors", org_id, web_id))

    async def delete_record(record):
        events.append(("database", record.id))

    async def bump_content_version(_org_id):
        events.append(("version", 7))

    monkeypatch.setattr(ingest_route, "_delete_document_vectors", delete_vectors)
    monkeypatch.setattr(ingest_route, "_bump_content_version", bump_content_version)
    db.delete = delete_record

    result = asyncio.run(
        delete_document(
            document_id=51,
            current_user=SimpleNamespace(id=3),
            db=db,
        )
    )

    assert result["message"].startswith("Document 51")
    assert events == [("vectors", 7, 19), ("database", 19), ("version", 7)]
    assert db.committed


def test_delete_document_keeps_database_record_if_vector_cleanup_fails(monkeypatch):
    db = FakeManagementDatabase()

    async def fail_delete_vectors(_org_id, _web_id):
        raise RuntimeError("Qdrant unavailable")

    monkeypatch.setattr(ingest_route, "_delete_document_vectors", fail_delete_vectors)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            delete_document(
                document_id=51,
                current_user=SimpleNamespace(id=3),
                db=db,
            )
        )

    assert error.value.status_code == 503
    assert db.deleted == []
    assert not db.committed
