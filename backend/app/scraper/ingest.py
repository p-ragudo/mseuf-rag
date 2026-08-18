import os
import glob
import re
from pathlib import Path
from typing import List
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.services.ingestion.schema import RawChunk

BASE_DIR = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE_BASE_DIR = BASE_DIR / "data" / "knowledge_base"

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
    """Reads all markdown files from knowledge_base and converts them into RawChunk models."""
    md_files = glob.glob(str(KNOWLEDGE_BASE_DIR / "*.md"))
    print(f"Loading {len(md_files)} Markdown files from {KNOWLEDGE_BASE_DIR}...")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        separators=["\n\n", "\n", ". ", " ", ""]
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
            title = doc_id.replace("mseuf_edu_ph_", "").replace("_", " ").replace("-", " ").title()
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
                            chunk_id=f"chunk_{chunk_counter:06d}",
                            document_id=doc_id,
                            source_url=source_url,
                            title=title,
                            content=text.strip()
                        )
                    )
                    chunk_counter += 1

        except Exception as e:
            print(f"[Error] Failed to process {file_path}: {e}")

    print(f"Successfully generated {len(raw_chunks)} RawChunk objects ready for QGen.")
    return raw_chunks

if __name__ == "__main__":
    chunks = load_and_chunk_knowledge_base()