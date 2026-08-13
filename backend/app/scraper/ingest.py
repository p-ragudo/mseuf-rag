import os
import glob
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Dynamic path pointing to backend/data/knowledge_base
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KNOWLEDGE_BASE_DIR = os.path.join(BASE_DIR, "data", "knowledge_base")

def process_knowledge_base():
    """Loads markdown files from knowledge_base and splits them into chunks for RAG."""
    md_files = glob.glob(os.path.join(KNOWLEDGE_BASE_DIR, "*.md"))
    print(f"Found {len(md_files)} Markdown files in: {KNOWLEDGE_BASE_DIR}")

    if not md_files:
        print("No markdown files found. Ensure backend/data/knowledge_base contains .md files.")
        return []

    # Text splitter optimized for RAG semantic search / vector retrieval
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,        # Character limit per chunk
        chunk_overlap=150,     # Context overlap window
        separators=["\n\n", "\n", " ", ""]
    )

    all_chunks = []

    for file_path in md_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            source_url = "Unknown"
            # Extract source URL from frontmatter metadata
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].split("\n"):
                        if line.startswith("source_url:"):
                            source_url = line.replace("source_url:", "").strip()
                    content = parts[2]

            # Generate chunks with source metadata attached
            chunks = text_splitter.create_documents(
                texts=[content],
                metadatas=[{
                    "source_url": source_url, 
                    "file_name": os.path.basename(file_path)
                }]
            )
            all_chunks.extend(chunks)

        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    print(f"Chunking complete. Created {len(all_chunks)} semantic chunks for vector indexing.")
    return all_chunks

if __name__ == "__main__":
    process_knowledge_base()