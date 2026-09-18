import glob
import os
import re
from pathlib import Path
from typing import List

from app.services.llm_qgen.schema import RawChunk #removed backend.
from langchain_text_splitters import RecursiveCharacterTextSplitter

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"


def clean_markdown_content(text: str) -> str:
    """Strips unnecessary HTML tags and excess whitespace."""
    # Strip HTML tags if any leaked through
    text = re.sub(r"<[^>]+>", " ", text)
    # Strip repetitive Markdown link noise/formatting like [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Normalize excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_and_chunk_knowledge_base() -> List[RawChunk]:
    """Reads all markdown files from the data directory and converts them into RawChunk models."""
    # Recursively find all .md files in the data directory
    md_files = [str(p) for p in DATA_DIR.rglob("*.md")]
    print(f"Loading {len(md_files)} Markdown files from {DATA_DIR}...")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    raw_chunks: List[RawChunk] = []
    chunk_counter = 1

    for file_path in md_files:
        doc_filename = os.path.basename(file_path)
        doc_id = os.path.splitext(doc_filename)[0]

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_content = f.read()

            source_url = "https://mseuf.edu.ph"
            title = (
                doc_id.replace("mseuf_edu_ph_", "")
                .replace("portal_mseuf_edu_ph_", "")
                .replace("_", " ")
                .replace("-", " ")
                .title()
            )
            content = raw_content

            # Parse frontmatter metadata if present
            if raw_content.startswith("---"):
                parts = raw_content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].split("\n"):
                        if line.startswith("source_url:"):
                            source_url = line.replace("source_url:", "").strip()
                        elif line.startswith("title:"):
                            title = line.replace("title:", "").strip()
                    content = parts[2]

            content = clean_markdown_content(content)
            if not content:
                continue

            # Split document text into chunks
            split_texts = text_splitter.split_text(content)

            for text in split_texts:
                if len(text.strip()) > 40:  # Skip trivial fragments
                    raw_chunks.append(
                        RawChunk(
                            id=f"chunk_{chunk_counter:06d}",
                            doc_id=doc_id,
                            source_url=source_url,
                            title=title,
                            content=text.strip(),
                            tags=[],
                        )
                    )
                    chunk_counter += 1

        except Exception as e:
            print(f"[Error] Failed to process {file_path}: {e}")

    print(f"Successfully generated {len(raw_chunks)} RawChunk objects ready for QGen.")
    return raw_chunks


if __name__ == "__main__":
    chunks = load_and_chunk_knowledge_base()