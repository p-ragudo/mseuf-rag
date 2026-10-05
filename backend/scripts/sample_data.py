from typing import List

from app.services.llm_qgen.schema import RawChunk
from app.utils.uuid_generator import generate_chunk_id
from app.utils.uuid_generator import generate_doc_id

# Add / customize test chunks here
SAMPLE_CHUNKS: List[RawChunk] = [
    RawChunk(
        id=generate_chunk_id(
            source_url="https://example.edu/registrar/shifting",
            chunk_index=0,
            content="Students applying for a shift of program must submit their approved Shifting Form to the Registrar by week 3 of the semester."
        ),
        doc_id=generate_doc_id(source_url="https://example.edu/registrar/shifting"),
        source_url="https://example.edu/registrar/shifting",
        title="College Shifting Procedures",
        content="Students applying for a shift of program must submit their approved Shifting Form to the Registrar by week 3 of the semester.",
        tags=["Registrar", "Academic Policy", "Undergraduate"],
    ),
    RawChunk(
        id=generate_chunk_id(
            source_url="https://example.edu/scholarships/guidelines",
            chunk_index=0,
            content="To maintain an academic scholarship, students must have a general weighted average of 1.75 or higher with no failing grades."
        ),
        doc_id=generate_doc_id(source_url="https://example.edu/scholarships/guidelines"),
        source_url="https://example.edu/scholarships/guidelines",
        title="Academic Scholarship Guidelines",
        content="To maintain an academic scholarship, students must have a general weighted average of 1.75 or higher with no failing grades.",
        tags=["Scholarships", "Financial Aid", "Requirements"],
    ),
]
