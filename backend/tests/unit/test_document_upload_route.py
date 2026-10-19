import asyncio
import io
from types import SimpleNamespace

from docx import Document
from fastapi import BackgroundTasks, UploadFile

from app.models.scraped_page import PageProcessStatus, ScrapedPage
from app.models.website import Website, WebsiteScrapeStatus
from app.routes.ingest import get_document_ingestion_status, upload_document


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
    def __init__(self, row=None, counts=(0, 0, 0)):
        self.row = row
        self.counts = counts

    def one_or_none(self):
        return self.row

    def one(self):
        return self.counts


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
