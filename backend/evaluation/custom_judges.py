"""LLM-as-judge rubrics:
  1. Reference-Guided Judge (for the 100 Synthetic & 21 FAQ QA pairs)
  2. Reference-Free RAG Triad Judge (for the 71 Real-User queries with no ground-truth reference)
  3. Abstention Judge (for negative/unanswerable queries)
"""
import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.core.config import settings

JUDGE_CONCURRENCY = 3


class AnswerJudgeScore(BaseModel):
    groundedness: float = Field(description="0.0, 0.25, 0.5, 0.75, or 1.0")
    completeness: float = Field(description="0.0, 0.25, 0.5, 0.75, or 1.0")
    helpfulness: float = Field(description="0.0, 0.25, 0.5, 0.75, or 1.0")
    context_sufficiency: float = Field(description="0.0, 0.25, 0.5, 0.75, or 1.0")
    brief_rationale: str = Field(description="One sentence explaining any deduction.")


class ReferenceFreeJudgeScore(BaseModel):
    groundedness: float = Field(description="0.0, 0.25, 0.5, 0.75, or 1.0: are claims supported by contexts?")
    helpfulness: float = Field(description="0.0, 0.25, 0.5, 0.75, or 1.0: does it directly address the user query?")
    context_sufficiency: float = Field(description="0.0, 0.25, 0.5, 0.75, or 1.0: do contexts contain the answer?")
    brief_rationale: str = Field(description="One sentence explaining the verdict.")


class AbstentionVerdict(BaseModel):
    abstained: bool = Field(description="True if the response declines / says the information is not available.")
    asserted_unsupported_facts: bool = Field(
        description="True if the response states concrete facts (fees, dates, policies...) that are not in the contexts."
    )
    brief_rationale: str


ANSWER_RUBRIC = """You are an impartial, rigorous RAG evaluation judge. Score ONE test execution.
Use only these values for every score: 0.0, 0.25, 0.5, 0.75, 1.0.

groundedness - are the response's factual claims supported by the Retrieved Contexts?
  1.0 every claim/number/date/step is supported; 0.5 mostly supported with minor unsupported additions;
  0.0 contains claims absent from or contradicting the contexts.
completeness - compared with the Reference Answer, does the response contain its key facts/steps/conditions?
  1.0 all; 0.5 about half or key steps missing; 0.0 misses the core answer. Correct extra detail is NOT penalised.
  Different wording of the same fact counts as covered.
helpfulness - does the response directly and clearly answer the User Query, with correct branch/campus/level scope?
  1.0 direct and actionable; 0.0 refuses although the contexts contained the answer, or is confusing.
context_sufficiency - judging ONLY the Retrieved Contexts, do they contain the evidence needed to answer the query?
  1.0 complete unambiguous evidence; 0.5 partial (e.g. part of a list missing); 0.0 irrelevant or empty.
Judge each score independently."""

REFERENCE_FREE_RUBRIC = """You are an impartial RAG evaluation judge evaluating a real user query WITHOUT a pre-written reference answer.
Use only these values for every score: 0.0, 0.25, 0.5, 0.75, 1.0.

groundedness - are all factual claims in the Response strictly supported by the Retrieved Contexts? (If the response honestly states that specific details are not in the documents, groundedness is 1.0).
helpfulness - is the Response clear, direct, polite, and appropriately scoped (including asking a helpful clarification if the user query was vague or conversational)?
context_sufficiency - judging ONLY the Retrieved Contexts, how well do they contain the information needed to answer the User Query?"""

ABSTENTION_RUBRIC = """You judge whether an assistant correctly REFUSED to answer a question that its knowledge base does
not cover. Given the question, the retrieved contexts and the response, decide:
  abstained: the response says the information is unavailable / cannot be answered from the documents (a partial
             'here is what I do know about a related topic' that does not claim to answer the question still counts
             as abstained).
  asserted_unsupported_facts: the response states concrete facts that answer the question but are NOT in the contexts."""


def _client():
    api_key = settings.llm_qa_api_key or settings.llm_qgen_api_key
    return genai.Client(api_key=api_key)


async def _generate_json(
    client, model: str, system_instruction: str, prompt: str, schema, attempts: int = 3
) -> Optional[Dict[str, Any]]:
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            resp = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.0,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            if resp.text:
                return json.loads(resp.text)
            last = ValueError("empty judge response")
        except Exception as e:  # noqa: BLE001
            last = e
        await asyncio.sleep(2.5 * (2 ** attempt))
    print(f"  [Judge Error] {last}")
    return None


def _clamp(v: Any) -> Optional[float]:
    try:
        return round(min(1.0, max(0.0, float(v))), 4)
    except (TypeError, ValueError):
        return None


async def run_answer_judges(rows: List[Dict[str, Any]], judge_model: str) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """Scores rows that have a ground-truth reference answer (100 Synthetic + 21 FAQs)."""
    client = _client()
    sem = asyncio.Semaphore(JUDGE_CONCURRENCY)
    out: Dict[str, Dict[str, Any]] = {}
    failed = 0

    async def one(row: Dict[str, Any]) -> None:
        nonlocal failed
        ctx = "\n---\n".join(row["retrieved_contexts"])
        prompt = (
            f"User Query:\n{row['user_input']}\n\n"
            f"Reference Answer:\n{row['reference']}\n\n"
            f"Retrieved Contexts:\n{ctx}\n\n"
            f"Response to judge:\n{row['response']}\n"
        )
        async with sem:
            parsed = await _generate_json(client, judge_model, ANSWER_RUBRIC, prompt, AnswerJudgeScore)
            await asyncio.sleep(0.3)
        if not parsed:
            failed += 1
            return
        out[row["test_id"]] = {
            "groundedness": _clamp(parsed.get("groundedness")),
            "completeness": _clamp(parsed.get("completeness")),
            "helpfulness": _clamp(parsed.get("helpfulness")),
            "context_sufficiency": _clamp(parsed.get("context_sufficiency")),
            "judge_rationale": parsed.get("brief_rationale", ""),
        }

    await asyncio.gather(*(one(r) for r in rows))
    return out, failed


async def run_reference_free_judges(rows: List[Dict[str, Any]], judge_model: str) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """Scores the 71 unlabeled real-user queries using the Reference-Free RAG Triad."""
    client = _client()
    sem = asyncio.Semaphore(JUDGE_CONCURRENCY)
    out: Dict[str, Dict[str, Any]] = {}
    failed = 0

    async def one(row: Dict[str, Any]) -> None:
        nonlocal failed
        ctx = "\n---\n".join(row["retrieved_contexts"])
        prompt = (
            f"User Query:\n{row['user_input']}\n\n"
            f"Retrieved Contexts:\n{ctx}\n\n"
            f"Response to judge:\n{row['response']}\n"
        )
        async with sem:
            parsed = await _generate_json(client, judge_model, REFERENCE_FREE_RUBRIC, prompt, ReferenceFreeJudgeScore)
            await asyncio.sleep(0.3)
        if not parsed:
            failed += 1
            return
        out[row["test_id"]] = {
            "groundedness": _clamp(parsed.get("groundedness")),
            "helpfulness": _clamp(parsed.get("helpfulness")),
            "context_sufficiency": _clamp(parsed.get("context_sufficiency")),
            "judge_rationale": parsed.get("brief_rationale", ""),
        }

    await asyncio.gather(*(one(r) for r in rows))
    return out, failed


async def run_abstention_judges(rows: List[Dict[str, Any]], judge_model: str) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """Scores negative/unanswerable rows that the pipeline answered with the LLM."""
    client = _client()
    sem = asyncio.Semaphore(JUDGE_CONCURRENCY)
    out: Dict[str, Dict[str, Any]] = {}
    failed = 0

    async def one(row: Dict[str, Any]) -> None:
        nonlocal failed
        ctx = "\n---\n".join(row["retrieved_contexts"])
        prompt = (
            f"Question:\n{row['user_input']}\n\nRetrieved Contexts:\n{ctx}\n\nResponse:\n{row['response']}\n"
        )
        async with sem:
            parsed = await _generate_json(client, judge_model, ABSTENTION_RUBRIC, prompt, AbstentionVerdict)
            await asyncio.sleep(0.3)
        if not parsed:
            failed += 1
            return
        out[row["test_id"]] = {
            "abstained": bool(parsed.get("abstained")),
            "asserted_unsupported_facts": bool(parsed.get("asserted_unsupported_facts")),
            "judge_rationale": parsed.get("brief_rationale", ""),
        }

    await asyncio.gather(*(one(r) for r in rows))
    return out, failed