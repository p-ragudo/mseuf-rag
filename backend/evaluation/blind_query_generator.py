"""Blind Query Generation Step.

Transforms the 100 structured synthetic entries (`ground_truth_100.jsonl`) and the 21 FAQ entries
(`ground_truth_faqs_21.jsonl`) into blind, multilingual user-style queries (English, Tagalog, Taglish).
Real-user queries are unaffected.

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

DEFAULT_BLIND_MODEL = "gemini-2.5-flash"
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
        description="Natural, realistic user question seeking the target facts without copying official phrasing."
    )


class BlindQueryBatch(BaseModel):
    items: List[BlindQueryItem]


BLIND_SYSTEM_INSTRUCTION = """You are a Blind User-Query Simulator for evaluating a university RAG system.
You are NEVER shown the source document chunks. Instead, you are given ONLY:
  - Target Facts (the information the user needs to find out)
  - Scope (campus/branch, academic level, time period, difficulty tier)
  - Persona
  - Language Constraint (English, Tagalog, or Taglish)
  - Taboo Phrases (exact document titles or boilerplate phrases you MUST NOT copy)

CRITICAL RULES:
1. Formulate ONE natural, realistic question that a real person (matching the Persona) would type into a chat box to learn the Target Facts. The question MUST be written in the specified Language Constraint.
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
        for idx, r in enumerate(batch):
            persona = PERSONAS[(i + idx) % len(PERSONAS)]
            language = LANGUAGES[(i + idx) % len(LANGUAGES)]
            taboo = ", ".join(f'"{t}"' for t in _extract_taboo_phrases(r))
            scope = (
                f"Campus/Dept: {r.get('campus') or 'main'} | "
                f"Level: {r.get('academic_level') or 'general'} | "
                f"Period: {r.get('doc_period') or 'current'} | "
                f"Difficulty: {r.get('difficulty', 'easy')}"
            )
            # Blind constraint: neither ground_truth_contexts nor user_query is passed to the LLM
            prompt_blocks.append(
                f"--- ITEM test_id: {r['test_id']} ---\n"
                f"Persona: {persona}\n"
                f"Language Constraint: {language}\n"
                f"Scope: {scope}\n"
                f"Taboo Phrases to Avoid Verbatim: [{taboo}]\n"
                f"Target Facts the User Wants to Know:\n{r.get('ground_truth_answer')}\n"
            )

        prompt = (
            f"Generate 1 blind, natural user query for each of the {len(batch)} items below.\n\n"
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
            rec_copy["query_mode"] = "blind"
            updated_records.append(rec_copy)

        print(f"  [Blind Query Gen] {min(i + batch_size, len(records))}/{len(records)} complete")
        await asyncio.sleep(0.4)

    return updated_records


async def main() -> None:
    p = argparse.ArgumentParser(description="Generate blind queries for the 100 synthetic and 21 FAQ datasets.")
    p.add_argument("--org-id", type=int, default=1)
    p.add_argument("--input", default="ground_truth_100.jsonl")
    p.add_argument("--output", default="ground_truth_100_blind.jsonl")
    p.add_argument("--faq-input", default="ground_truth_faqs_21.jsonl")
    p.add_argument("--faq-output", default="ground_truth_faqs_21_blind.jsonl")
    p.add_argument("--model", default=DEFAULT_BLIND_MODEL)
    args = p.parse_args()

    d = tenant_dir(args.org_id, create=True)
    in_path = d / args.input
    if not in_path.exists():
        raise FileNotFoundError(f"{in_path} not found. Run `uv run python -m evaluation.generate_ground_truth --org-id {args.org_id} --overwrite` first.")

    print(f"Generating 100 multilingual blind queries from {in_path.name} ...")
    syn_records = read_jsonl(in_path)[:100]
    blind_syn = await generate_blind_queries_for_list(syn_records, model_name=args.model)
    out_path = d / args.output
    write_jsonl(out_path, blind_syn)
    print(f"[Done] Wrote {len(blind_syn)} blind synthetic queries to {out_path.resolve()}")

    faq_in = d / args.faq_input
    if faq_in.exists():
        print(f"\nGenerating 21 multilingual blind FAQ queries from {faq_in.name} ...")
        faq_records = read_jsonl(faq_in)[:21]
        blind_faqs = await generate_blind_queries_for_list(faq_records, model_name=args.model)
        faq_out = d / args.faq_output
        write_jsonl(faq_out, blind_faqs)
        print(f"[Done] Wrote {len(blind_faqs)} blind FAQ queries to {faq_out.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())