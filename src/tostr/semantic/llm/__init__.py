from __future__ import annotations
from .base import LLMClient, LLMResponse, LLMStrategy
from .gemini import GeminiStrategy
from .ollama import OllamaStrategy
from .prompts import CLASS_SYSTEM_INSTRUCTION, FILE_SYSTEM_INSTRUCTION, DIRECTORY_SYSTEM_INSTRUCTION
