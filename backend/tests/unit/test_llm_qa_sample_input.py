import asyncio
import sys
from pathlib import Path

# Ensure the backend root is in sys.path so app imports resolve properly
current_dir = Path(__file__).resolve().parent
backend_root = current_dir.parent if current_dir.name == "scripts" else current_dir
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.services.llm_qa.factory import get_qa_synthesizer
from app.services.llm_qa.schema import QARequest, RetrievedContextItem, QAResponse


async def test_rag_qa_flow() -> None:
    print("--- 1. Initializing QA Synthesizer ---")
    synthesizer = get_qa_synthesizer()
    print(f"Loaded synthesizer: {synthesizer.__class__.__name__}\n")

    print("--- 2. Mocking Retrieved Contexts & Query ---")
    mock_contexts = [
        RetrievedContextItem(
            title="University Admission Requirements",
            content=(
                "First-year applicants must submit Form 138 (Report Card), "
                "Certificate of Good Moral Character, 2x2 ID pictures, and PSA Birth Certificate. "
                "The application fee is PHP 350 for local students."
            ),
            source_url="https://admission.mseuf.edu.ph/requirements",
        ),
        RetrievedContextItem(
            title="Admissions Office Schedule & Location",
            content=(
                "The Admissions Office is located at the Student Services Building, Room 102. "
                "Office hours are from Monday to Friday, 8:00 AM to 5:00 PM."
            ),
            source_url="https://admission.mseuf.edu.ph/contact",
        ),
    ]

    sample_query = "What documents do I need to prepare as a freshman applicant, and where is the office located?"

    request_payload = QARequest(
        query=sample_query,
        contexts=mock_contexts,
    )

    print(f"Query: {request_payload.query}")
    print(f"Context Passages: {len(request_payload.contexts)}\n")

    print("--- 3. Invoking LLM QA Service ---")
    response: QAResponse = await synthesizer.generate_answer(request_payload)

    print("\n================ RAG RESPONSE ================")
    print(response.answer)
    print("==============================================")
    print("\nSources Cited:")
    for source in response.sources:
        print(f" - {source}")


if __name__ == "__main__":
    asyncio.run(test_rag_qa_flow())