"""Blind Query Generation Step.

Generates blind queries strictly matching the assigned language (English, Tagalog, or Taglish)
for both the 150 Synthetic QA pairs and the 63 Official FAQs:
  - 150 Synthetic -> 50 English, 50 Tagalog, 50 Taglish blind queries
  - 63 FAQs       -> 21 English, 21 Tagalog, 21 Taglish blind queries
  - Real-user queries are excluded and kept untouched.

Usage:
  uv run python -m evaluation.blind_query_generator --org-id 1
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from evaluation.common import read_jsonl, tenant_dir, write_jsonl

DEFAULT_BLIND_MODEL = "gemini-3.1-flash-lite"
PERSONAS = [
    "a high school senior casually asking in everyday student tone",
    "a parent asking a practical, direct question without administrative jargon",
    "a transfer student asking in a natural conversational tone",
    "a working professional or graduate applicant typing a quick mobile chat inquiry",
    "a currently enrolled college student asking a peer-style question",
]
LANGUAGES = ["English", "Tagalog", "Taglish"]


class BlindQueryItem(BaseModel):
    test_id: str
    blind_query: str = Field(
        description="Natural, realistic user question seeking the target facts in the specified language, without copying official phrasing."
    )


class BlindQueryBatch(BaseModel):
    items: List[BlindQueryItem]


BLIND_SYSTEM_INSTRUCTION = """You are a Blind User-Query Simulator for evaluating a university RAG system.
You are NEVER shown the source document chunks. Instead, you are given ONLY:
  - Target Facts (the information the user needs to find out)
  - Scope (campus/branch, academic level, time period, difficulty tier)
  - Persona
  - Target Language (English, Tagalog, or Taglish)
  - Taboo Phrases (exact document titles or boilerplate phrases you MUST NOT copy)

CRITICAL RULES:
1. Formulate ONE natural, realistic question that a real person (matching the Persona) would type into a chat box to learn the Target Facts. The question MUST strictly be written in the specified Target Language.
   - If English: Use natural, conversational student/parent English without formal admin phrasing.
   - If Tagalog: Use natural conversational Filipino/Tagalog (e.g., "Kailan po ang pasahan ng...", "Ano ang mga kailangang dalhin para sa...").
   - If Taglish: Use authentic conversational code-switching (e.g., "Pwede po ba mag-apply for transfer kahit...", "Magkano po tuition fee kapag...").
2. DELIBERATELY AVOID exact keyword sequences, formal document headings, and administrative phrasing mannerisms from the Taboo Phrases. Use everyday synonyms and natural phrasing instead.
3. Preserve essential disambiguating scope (such as the specific branch campus like Catanauan/Calauag/Candelaria, grade level, or year/date) so the question remains specific and answerable by the Target Facts.
4. For Medium (cross-referencing) and Hard (multi-hop/calculation/aggregation) items, ask a natural question that requires comparing or combining all the target facts."""


def _extract_taboo_phrases(record: Dict[str, Any]) -> List[str]:
    taboo: List[str] = []
    heading = (record.get("heading_path") or "").strip()
    if heading:
        for part in heading.split("|"):
            p = part.strip()
            if len(p) > 5:
                taboo.append(p)
    for phrase in (
        "Admission Officer-In-Charge",
        "Basic Education Department",
        "office transactions",
        "embodied by",
        "pursuant to",
        "in observance of",
        "Sustainable Development Goals",
    ):
        taboo.append(phrase)
    return taboo[:6]


async def generate_blind_queries_for_list(
    records: List[Dict[str, Any]],
    model_name: str = DEFAULT_BLIND_MODEL,
    batch_size: int = 10,
) -> List[Dict[str, Any]]:
    api_key = settings.llm_qa_api_key or settings.llm_qgen_api_key
    client = genai.Client(api_key=api_key)
    updated_records: List[Dict[str, Any]] = []

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        prompt_blocks: List[str] = []
        item_languages: Dict[str, str] = {}

        for idx, r in enumerate(batch):
            persona = PERSONAS[(i + idx) % len(PERSONAS)]
            target_language = r.get("language") or LANGUAGES[(i + idx) % len(LANGUAGES)]
            item_languages[r["test_id"]] = target_language

            taboo = ", ".join(f'"{t}"' for t in _extract_taboo_phrases(r))
            scope = (
                f"Campus/Dept: {r.get('campus') or 'main'} | "
                f"Level: {r.get('academic_level') or 'general'} | "
                f"Period: {r.get('doc_period') or 'current'} | "
                f"Difficulty: {r.get('difficulty', 'easy')}"
            )
            # Neither ground_truth_contexts nor user_query is passed to the LLM
            prompt_blocks.append(
                f"--- ITEM test_id: {r['test_id']} ---\n"
                f"Persona: {persona}\n"
                f"Target Language: {target_language}\n"
                f"Scope: {scope}\n"
                f"Taboo Phrases to Avoid Verbatim: [{taboo}]\n"
                f"Target Facts the User Wants to Know:\n{r.get('ground_truth_answer')}\n"
            )

        prompt = (
            f"Generate 1 blind, natural user query for each of the {len(batch)} items below matching its assigned Target Language.\n\n"
            + "\n".join(prompt_blocks)
        )

        parsed_map: Dict[str, str] = {}
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=BLIND_SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=BlindQueryBatch,
                        temperature=0.5,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    ),
                )
                if resp.text:
                    data = json.loads(resp.text)
                    for item in data.get("items", []):
                        parsed_map[item["test_id"]] = item["blind_query"].strip()
                    break
            except Exception as e:  # noqa: BLE001
                print(f"  [Blind Query Retry {attempt + 1}/3] {e}")
                await asyncio.sleep(2.5 * (2 ** attempt))

        for r in batch:
            rec_copy = dict(r)
            base_q = (rec_copy.get("base_user_query") or rec_copy.get("user_query") or "").strip()
            blind_q = parsed_map.get(r["test_id"]) or base_q
            rec_copy["base_user_query"] = base_q
            rec_copy["blind_user_query"] = blind_q
            rec_copy["user_query"] = blind_q
            rec_copy["language"] = item_languages.get(r["test_id"], rec_copy.get("language", "English"))
            rec_copy["query_mode"] = "blind"
            updated_records.append(rec_copy)

        print(f"  [Blind Query Gen] {min(i + batch_size, len(records))}/{len(records)} complete")
        await asyncio.sleep(0.4)

    return updated_records


async def main() -> None:
    p = argparse.ArgumentParser(description="Generate blind queries in English, Tagalog, and Taglish for Synthetic (50 each) and FAQs (21 each).")
    p.add_argument("--org-id", type=int, default=1)
    p.add_argument("--input", default="ground_truth_150.jsonl")
    p.add_argument("--output", default="ground_truth_150_blind.jsonl")
    p.add_argument("--faq-input", default="ground_truth_faqs_63.jsonl")
    p.add_argument("--faq-output", default="ground_truth_faqs_63_blind.jsonl")
    p.add_argument("--model", default=DEFAULT_BLIND_MODEL)
    args = p.parse_args()

    d = tenant_dir(args.org_id, create=True)

    # 1. Generate 150 Synthetic Blind Queries
    in_path = d / args.input
    if in_path.exists():
        print(f"Generating 150 blind synthetic queries (50 English, 50 Tagalog, 50 Taglish) from {in_path.name}...")
        syn_records = read_jsonl(in_path)[:150]
        blind_syn = await generate_blind_queries_for_list(syn_records, model_name=args.model)
        out_path = d / args.output
        write_jsonl(out_path, blind_syn)
        syn_counts = {lang: sum(1 for r in blind_syn if r.get("language") == lang) for lang in LANGUAGES}
        print(f"[Done] Wrote {len(blind_syn)} blind synthetic queries to {out_path.resolve()}")
        print(f"       Breakdown: {syn_counts}\n")
    else:
        print(f"[Warning] {in_path.name} not found. Run generate_ground_truth.py first.")

    # 2. Generate 63 FAQ Blind Queries
    faq_in = d / args.faq_input
    if faq_in.exists():
        print(f"Generating 63 blind FAQ queries (21 English, 21 Tagalog, 21 Taglish) from {faq_in.name}...")
        faq_records = read_jsonl(faq_in)[:63]
        blind_faqs = await generate_blind_queries_for_list(faq_records, model_name=args.model)
        faq_out = d / args.faq_output
        write_jsonl(faq_out, blind_faqs)
        faq_counts = {lang: sum(1 for r in blind_faqs if r.get("language") == lang) for lang in LANGUAGES}
        print(f"[Done] Wrote {len(blind_faqs)} blind FAQ queries to {faq_out.resolve()}")
        print(f"       Breakdown: {faq_counts}\n")
    else:
        print(f"[Warning] {faq_in.name} not found. Run generate_ground_truth.py first.")


if __name__ == "__main__":
    asyncio.run(main())