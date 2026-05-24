from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tostr.llm.base import LLMStrategy, LLMResponse

class MethodDescription(BaseModel):
    method_id: int = Field(description="The integer ID of the method provided in the prompt data")
    description: str = Field(description="Description of the method")
    
class DescriptionResult(BaseModel):
    uid: str = Field(description="uid of the class")
    description: str = Field(description="Description of the class")
    methods: list[MethodDescription] = Field(description="List of method information")

class GeminiStrategy(LLMStrategy):
    def __init__(self, api_key: str, model_name: str = "gemini-3.1-flash-lite", max_concurrent_requests: int = 200):
        super().__init__(api_key, model_name, max_concurrent_requests)
        self.client = genai.Client(api_key=api_key)

    async def describe_class(self, input_data_string: str, system_instruction: str) -> LLMResponse:
        # Note: LLMClient handles retries and semaphore
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=input_data_string,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_json_schema=DescriptionResult.model_json_schema(),
                    temperature=0.2,
                    max_output_tokens=8192
                )
            )
            
            parsed_data = response.parsed
            
            # Map DescriptionResult to LLMResponse
            description_map = {int(m.get("method_id")): m.get("description") for m in parsed_data.get("methods", []) if m.get("method_id") is not None}
            
            return LLMResponse(
                uid=parsed_data.get("uid", ""),
                description=parsed_data.get("description", ""),
                description_map=description_map,
                status="success"
            )
        except Exception as e:
            # Re-raise to let LLMClient handle retries for 503/429
            raise e
