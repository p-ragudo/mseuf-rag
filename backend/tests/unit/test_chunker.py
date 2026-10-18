import unittest
from pathlib import Path

# Resolve the backend root directory (backend/) relative to this file (backend/tests/unit/test_chunker.py)
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

# Import chunker directly from the app package or load via path resolved to backend root
import sys
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ingest_pipeline.chunker import (
    chunk_markdown,
    estimate_token_count,
    is_substantive_chunk,
)


class TestChunker(unittest.TestCase):
    def test_estimate_token_count(self):
        text = "This is a simple sample text for testing token estimation."
        count = estimate_token_count(text)
        self.assertEqual(count, len(text.split()))

    def test_estimate_token_count_empty(self):
        self.assertEqual(estimate_token_count(""), 1)

    def test_is_substantive_chunk_valid(self):
        valid_text = (
            "Enrollment for the upcoming academic year is now officially open. "
            "Students are required to submit their documents to the registrar."
        )
        self.assertTrue(is_substantive_chunk(valid_text))

    def test_is_substantive_chunk_short(self):
        short_text = "Too short"
        self.assertFalse(is_substantive_chunk(short_text))

    def test_is_substantive_chunk_boilerplate(self):
        boilerplate_text = (
            "Please read our cookie and privacy policy before continuing. "
            "All rights reserved by the institution website terms."
        )
        self.assertFalse(is_substantive_chunk(boilerplate_text))

    def test_chunk_markdown_empty(self):
        chunks = chunk_markdown("")
        self.assertEqual(chunks, [])

    def test_chunk_markdown_structure(self):
        md = """# Admissions

## Freshmen Requirements
1. Form 138 report card.
2. Certificate of Good Moral Character.
3. PSA Birth Certificate photocopy.
4. Two pieces 2x2 colored pictures.

## Transferee Requirements
1. Honorable Dismissal certificate.
2. Official Transcript of Records (TOR).
3. PSA Birth Certificate photocopy.
"""
        chunks = chunk_markdown(md, page_title="Admissions Guide")
        self.assertGreater(len(chunks), 0)
        self.assertTrue(all(hasattr(c, "content") for c in chunks))
        self.assertTrue(all(hasattr(c, "chunk_index") for c in chunks))
        self.assertTrue(all(hasattr(c, "section_id") for c in chunks))
        self.assertEqual(chunks[0].chunk_index, 0)


if __name__ == "__main__":
    unittest.main()