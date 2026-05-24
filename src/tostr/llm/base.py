import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel, Field
from loguru import logger

class LLMResponse(BaseModel):
    description: str = ""
    description_map: dict[int, str] = Field(default_factory=dict)
    status: str = "success"
    error: str = ""
    uid: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

class LLMStrategy(ABC):
    def __init__(self, api_key: str, model_name: str, max_concurrent_requests: int = 200):
        self.api_key = api_key
        self.model_name = model_name
        self.max_concurrent_requests = max_concurrent_requests
        self._semaphore = None

    @property
    def semaphore(self):
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        return self._semaphore

    @abstractmethod
    async def describe_class(self, input_data_string: str, system_instruction: str) -> LLMResponse:
        pass

class LLMClient:

    SYSTEM_INSTRUCTION = """
You are an expert senior software engineer and technical writer. 
Your goal is to generate high-quality, information-dense documentation for software methods to be consumed by an AI Agent.
The descriptions should be written in context; docs dont need to say 'this is a java class' or this is a method'.
Assume all descriptions are to be utilized by an AI Agent for contextual reference - optimize for LLM readability and token-dense contextual depth.

### TASK
Analyze the provided code and generate a JSON response. 
**Class Analysis**: Generate a `description` for the overall class. Look at the fields, Javadocs, and method summaries to write a concise explanation of the class's primary purpose and architectural role. Also provide a confidence score and context need score for the class.
**Method Analysis**: For each method that still has a raw code body, generate:
**Description**: Write a concise summary of what the method does. 
   - **Focus on**: Inputs and Outputs (semantics) and Side Effects (state changes). If the method is complex, include core logic (algorithms and data flow).
   - **Style**: Technical, precise, and dense. Start with an active verb (e.g., "Calculates...", "Updates..."). Unless complexity is high, try to keep it to one sentence.
Reference methods by their provided integer `method_id`.
"""

    def __init__(self, strategy: LLMStrategy):
        # Initialize your LLM client here (e.g., Gemini, OpenAI, etc.)
        self.strategy = strategy

    async def describe_class(self, class_obj: Any, imports: list[str]) -> LLMResponse:
        # Create a mapping of method IDs to method objects
        method_lookup = {idx: m for idx, m in enumerate(class_obj.methods)}

        input_data = {
            "code": class_obj.skeletonize(),
            "method_ids_to_signatures": {idx: m.signature for idx, m in method_lookup.items()}
        }

        input_data_string = json.dumps(input_data)

        logger.debug(f"Generating Description for {class_obj.uid}...")
        
        max_retries = 3
        base_delay = 2

        async with self.strategy.semaphore:
            for attempt in range(max_retries):
                try:
                    result = await self.strategy.describe_class(
                        input_data_string=input_data_string, 
                        system_instruction=self.SYSTEM_INSTRUCTION
                    )
                    
                    # Map method descriptions back to objects
                    if result.status == "success":
                        for idx_str, description in result.description_map.items():
                            try:
                                idx = int(idx_str)
                                if idx in method_lookup:
                                    method_lookup[idx].description = description
                            except (ValueError, TypeError):
                                continue
                    
                    return result
                except Exception as e:
                    error_str = str(e)
                    if "503" in error_str or "429" in error_str:
                        if attempt < max_retries - 1:
                            sleep_time = base_delay * (2 ** attempt)
                            logger.warning(f"⏳ Server busy (503/429) on {class_obj.uid}. Retrying in {sleep_time}s...")
                            await asyncio.sleep(sleep_time)
                            continue 
                            
                        return LLMResponse(
                            uid=class_obj.uid,
                            error=error_str,
                            status="error"
                        )
                    logger.error(f"Error describing class {class_obj.uid}: {error_str}")
                    return LLMResponse(
                        uid=class_obj.uid,
                        error=error_str,
                        status="error"
                    )
