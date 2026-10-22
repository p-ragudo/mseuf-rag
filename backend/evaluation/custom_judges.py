import asyncio
import json
from typing import Any, Dict, List

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.core.config import settings

JUDGE_BATCH_SIZE = 5


class CustomJudgeScoreItem(BaseModel):
    test_id: str = Field(description="The exact test_id of the evaluated sample.")
    groundedness: float = Field(
        description="0.0 to 1.0: Can every factual claim in the response be directly traced to the retrieved context without unsupported extrapolation?"
    )
    completeness: float = Field(
        description="0.0 to 1.0: Does the generated response cover all essential facts, steps, or requirements present in the ground_truth_answer?"
    )
    helpfulness: float = Field(
        description="0.0 to 1.0: Does the response directly, clearly, and actionably satisfy the user's inquiry intent?"
    )
    source_sufficiency: float = Field(
        description="0.0 to 1.0: Are the retrieved contexts and returned source URLs sufficient and relevant enough to answer the user's question?"
    )
    brief_rationale: str = Field(
        description="1-sentence diagnostic explanation of any deductions."
    )


class BatchCustomJudgeOutput(BaseModel):
    evaluations: List[CustomJudgeScoreItem] = Field(
        description="List of evaluation scores corresponding to each input test_id."
    )


JUDGE_SYSTEM_INSTRUCTION = """You are an impartial, rigorous RAG Evaluation Judge.
You will receive a batch of RAG test executions. For each item, score the following four metrics on a continuous scale from 0.0 to 1.0 (e.g., 0.0, 0.25, 0.5, 0.75, 1.0):

1. groundedness (0.0 - 1.0):
   - 1.0: Every single claim, number, date, or procedure in the Response is explicitly supported by the Retrieved Contexts.
   - 0.5: Partially grounded, but includes minor unverified extrapolations.
   - 0.0: Hallucinates facts not in the Retrieved Contexts or contradicts the context. (Note: A polite fallback saying information is unavailable when context is empty is 1.0 grounded).

2. completeness (0.0 - 1.0):
   - Compare the Response against the Ground Truth Reference Answer.
   - 1.0: Captures 100% of the key facts, steps, or conditions in the reference answer.
   - 0.5: Capturesroughly half of the necessary details or omits key steps.
   - 0.0: Misses the core answer completely.

3. helpfulness (0.0 - 1.0):
   - 1.0: Directly answers the User Query with clear formatting, appropriate branch/level specificity, and actionable clarity.
   - 0.0: Refuses to answer when context was present, is confusing, or fails to address user intent.

4. source_sufficiency (0.0 - 1.0):
   - 1.0: The Retrieved Contexts contain complete, unambiguous evidence required to answer the User Query, and the Ground Truth URL is represented.
   - 0.5: The Retrieved Contexts contain partial evidence (e.g., missing parts of a list).
   - 0.0: The Retrieved Contexts are irrelevant noise or empty.
"""


async def run_custom_judges_batch(
    samples: List[Dict[str, Any]],
    judge_model: str = "gemini-3.8-flash",
) -> Dict[str, Dict[str, Any]]:
    """
    Evaluates groundedness, completeness, helpfulness, and source_sufficiency
    in batches of 5 to maximize speed and minimize API quota usage.
    Returns mapping: test_id -> {groundedness, completeness, helpfulness, source_sufficiency, brief_rationale}
    """
    api_key = settings.llm_qa_api_key or settings.llm_qgen_api_key
    client = genai.Client(api_key=api_key)
    results_map: Dict[str, Dict[str, Any]] = {}

    for i in range(0, len(samples), JUDGE_BATCH_SIZE):
        batch = samples[i : i + JUDGE_BATCH_SIZE]
        blocks = []

        for item in batch:
            ctx_preview = "\n---\n".join(item.get("retrieved_contexts", []))[:6000]
            blocks.append(
                f"=== TEST_ID: {item['test_id']} ===\n"
                f"User Query: {item['user_input']}\n"
                f"Ground Truth URL: {item.get('gt_url', 'N/A')}\n"
                f"Retrieved URLs: {', '.join(item.get('retrieved_urls', [])) or 'None'}\n"
                f"Ground Truth Reference Answer:\n{item['reference']}\n\n"
                f"Retrieved Contexts:\n{ctx_preview}\n\n"
                f"Generated Response:\n{item['response']}\n"
                f"=== END TEST_ID: {item['test_id']} ==="
            )

        prompt = (
            f"Evaluate the following {len(batch)} RAG pipeline outputs independently:\n\n"
            + "\n\n".join(blocks)
        )

        response = None
        for attempt in range(3):
            try:
                response = await client.aio.models.generate_content(
                    model=judge_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=JUDGE_SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=BatchCustomJudgeOutput,
                        temperature=0.0,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
                break
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2.5 * (2 ** attempt))
                else:
                    print(f"  [Custom Judge Error] Batch {i}..{i+len(batch)}: {e}")

        if response and response.text:
            try:
                parsed = json.loads(response.text)
                for ev in parsed.get("evaluations", []):
                    tid = ev.get("test_id")
                    if tid:
                        results_map[tid] = {
                            "groundedness": round(float(ev.get("groundedness", 0.0)), 4),
                            "completeness": round(float(ev.get("completeness", 0.0)), 4),
                            "helpfulness": round(float(ev.get("helpfulness", 0.0)), 4),
                            "source_sufficiency": round(float(ev.get("source_sufficiency", 0.0)), 4),
                            "judge_rationale": ev.get("brief_rationale", ""),
                        }
            except Exception as e:
                print(f"  [Custom Judge Parse Error] Batch {i}..{i+len(batch)}: {e}")

        await asyncio.sleep(0.4)

    return results_map