# import os
# from openai import AsyncOpenAI
# from app.services.llm_qgen.base import BaseQuestionGenerator
# from app.services.llm_qgen.qgen import RawChunk, GeneratedQuestionSet
# from app.services.llm_qgen import SYSTEM_INSTRUCTION

# class OpenAICompatibleQuestionGenerator(BaseQuestionGenerator):
#     def __init__(
#         self,
#         model_name: str = "gpt-4o-mini",
#         base_url: str = None,
#         api_key: str = None,
#         temperature: float = 0.3,
#     ):
#         self.model_name = model_name
#         self.temperature = temperature
#         self.client = AsyncOpenAI(
#             api_key=api_key or os.getenv("OPENAI_API_KEY", "dummy-key"),
#             base_url=base_url or os.getenv("OPENAI_BASE_URL"),
#         )

#     async def generate_questions(self, chunk: RawChunk) -> GeneratedQuestionSet:
#         prompt = (
#             f"Page Title: {chunk.title}\n"
#             f"URL: {chunk.source_url}\n\n"
#             f"Content:\n{chunk.content}"
#         )
#         # client.beta.chat.completions.parse handles schema generation and validation
#         response = await self.client.beta.chat.completions.parse(
#             model=self.model_name,
#             messages=[
#                 {"role": "system", "content": SYSTEM_INSTRUCTION},
#                 {"role": "user", "content": prompt},
#             ],
#             response_format=GeneratedQuestionSet,
#             temperature=self.temperature,
#         )
#         return response.choices[0].message.parsed