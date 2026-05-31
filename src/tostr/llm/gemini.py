from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tostr.llm.base import LLMStrategy, LLMResponse

class GeminiStrategy(LLMStrategy):
    def __init__(self, api_key: str, model_name: str = "gemini-3.1-flash-lite", max_concurrent_requests: int = 200):
        super().__init__(api_key, model_name, max_concurrent_requests)
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    async def generate(self, input_data_string: str, system_instruction: str, response_schema: BaseModel):
        # Note: LLMClient handles retries and semaphore
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=input_data_string,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_json_schema=response_schema.model_json_schema(),
                    temperature=0.2,
                    max_output_tokens=8192
                )
            )

            return response_schema.model_validate_json(response.text)
        except Exception as e:
            # Re-raise to let LLMClient handle retries for 503/429
            raise e