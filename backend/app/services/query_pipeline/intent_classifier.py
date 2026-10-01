import json
from typing import List, Optional
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.core.config import settings


class QueryIntent(BaseModel):
    is_ambiguous: bool = Field(
        ...,
        description="True if the user query is broad and lacks necessary entity, campus, branch, or level specifics",
    )
    detected_sub_entity: Optional[str] = Field(
        default=None,
        description="Detected campus, branch, or sub-department name, or null if unspecified",
    )
    detected_academic_level: Optional[str] = Field(
        default=None,
        description="'undergraduate', 'graduate', 'shs', 'basic_ed', or null if not applicable",
    )
    clarification_message: Optional[str] = Field(
        default=None,
        description="Follow-up clarification to ask the user if the query is too ambiguous to answer definitively without context",
    )


class QueryClassifier:
    def __init__(self):
        api_key = settings.llm_qa_api_key or settings.llm_qgen_api_key
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-3.8-flash"

    async def classify_intent(
        self,
        query: str,
        org_name: str = "the institution",
        known_locations: Optional[List[str]] = None,
    ) -> QueryIntent:
        locations_hint = (
            f"Known campuses/branches/locations for this organization: {', '.join(known_locations)}."
            if known_locations
            else "The organization may have multiple branches, locations, or academic levels."
        )

        system_instruction = (
            f"You are a query intent classification engine for {org_name}. "
            f"{locations_hint}\n"
            "Analyze the user query. Determine if the user is asking a broad question (such as admission requirements, "
            "tuition fees, or program offerings) that typically depends on knowing the specific campus/branch or education level.\n"
            "If the query is broad and lacks necessary location or academic level context, set is_ambiguous=true and formulate "
            "a concise clarification message asking which specific location, campus, or level they are inquiring about.\n"
            "If the user specifies a location or if the question is general institutional policy, set is_ambiguous=false."
        )

        prompt = f"User Query: {query}"

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=QueryIntent,
                    temperature=0.0,
                    max_output_tokens=300,
                ),
            )
            data = json.loads(response.text)
            return QueryIntent(**data)
        except Exception as e:
            print(f"[QueryClassifier Warning] Intent classification bypassed: {e}")
            return QueryIntent(
                is_ambiguous=False,
                detected_sub_entity=None,
                detected_academic_level=None,
            )