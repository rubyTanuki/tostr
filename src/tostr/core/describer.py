from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING
from pydantic import BaseModel, Field
from loguru import logger

from tostr.core.models import BaseStruct, Directory, BaseFile, BaseClass, BaseMethod, BaseField
from tostr.semantic.llm import CLASS_SYSTEM_INSTRUCTION, FILE_SYSTEM_INSTRUCTION, DIRECTORY_SYSTEM_INSTRUCTION

if TYPE_CHECKING:
    from tostr.semantic.llm.base import LLMClient
    from tostr.semantic.embeddings.base import EmbeddingClient


class LLMDescriber:
    def __init__(self, llm: LLMClient, embedder: EmbeddingClient):
        self.llm = llm
        self.embedder = embedder

    async def describe(self, struct: BaseStruct):
        if isinstance(struct, Directory):
            await self._describe_directory(struct)
        elif isinstance(struct, BaseFile):
            await self._describe_file(struct)
        elif isinstance(struct, BaseClass):
            await self._describe_class(struct)
        elif isinstance(struct, BaseMethod):
            self._describe_method(struct)
        # BaseField: no description needed

    def _advance(self, struct: BaseStruct, phase: str, n: int = 1):
        tracker = getattr(getattr(struct, 'registry', None), 'progress_tracker', None)
        if tracker:
            tracker.advance(phase, n)

    def _handle_embed(self, struct: BaseStruct):
        if struct.vector is not None:
            self._advance(struct, 'embed', 1)
        else:
            self.embedder.enqueue(struct)

    async def _describe_directory(self, directory: Directory):
        # Early exit before recursion: if already described, children are assumed done too
        if directory.description:
            self._advance(directory, 'describe', 1)
            self._handle_embed(directory)
            return

        if directory.all_children:
            await asyncio.gather(*[self.describe(c) for c in directory.all_children])

        if not directory.all_children:
            directory.description = "Empty Directory"
            self._advance(directory, 'describe', 1)
            self._advance(directory, 'embed', 1)
            return

        if len(directory.all_children) == 1:
            directory.description = directory.all_children[0].description
            self._advance(directory, 'describe', 1)
            self._advance(directory, 'embed', 1)
            return

        logger.debug(f"Generating Description for directory {directory.uid}...")

        class DirectoryDescriptionSchema(BaseModel):
            description: str = Field(description="Description of the directory")

        response = await self.llm.generate_description(
            input_data={c.uid: c.description for c in directory.all_children},
            system_prompt=DIRECTORY_SYSTEM_INSTRUCTION,
            response_schema=DirectoryDescriptionSchema,
        )

        if not response:
            logger.warning(f"⚠️ Skipping {directory.uid} due to LLM failure")
            self._advance(directory, 'embed', 1)
            return

        directory.description = response.description
        self.embedder.enqueue(directory)
        logger.debug(f"Successfully Generated Description for directory {directory.uid}")

    async def _describe_file(self, file: BaseFile):
        # Recurse on non-method children (classes) first so their descriptions are ready
        non_methods = [c for c in file.all_children if not isinstance(c, BaseMethod)]
        if non_methods:
            await asyncio.gather(*[self.describe(c) for c in non_methods])

        if file.description:
            self._advance(file, 'describe', 1 + len(file.methods))
            self._handle_embed(file)
            for m in file.methods:
                if m.vector is not None:
                    self._advance(m, 'embed', 1)
                else:
                    self.embedder.enqueue(m)
            return

        if not file.all_children:
            file.description = "Empty File"
            self._advance(file, 'describe', 1)
            self._advance(file, 'embed', 1)
            return

        if len(file.all_children) == 1 and not isinstance(file.all_children[0], BaseMethod):
            file.description = file.all_children[0].description
            file.vector = file.all_children[0].vector
            self._advance(file, 'describe', 1)
            self._advance(file, 'embed', 1)
            return

        logger.debug(f"Generating Description for file {file.uid}...")

        method_lookup = {idx: m for idx, m in enumerate(file.methods) if not m.description}

        already_described = [m for m in file.methods if m.description]
        if already_described:
            self._advance(file, 'describe', len(already_described))
            for m in already_described:
                if m.vector is not None:
                    self._advance(m, 'embed', 1)
                else:
                    self.embedder.enqueue(m)

        class FileDescriptionSchema(BaseModel):
            description: str = Field(description="Description of the file")
            description_map: dict[str, str] = Field(default_factory=dict, description="Mapping of method_id to description")

        response = await self.llm.generate_description(
            input_data={
                "described_components": {c.uid: c.description for c in file.all_children if c.description},
                "un_described_methods": {str(idx): m.body for idx, m in method_lookup.items()},
            },
            system_prompt=FILE_SYSTEM_INSTRUCTION,
            response_schema=FileDescriptionSchema,
        )

        if not response:
            logger.warning(f"⚠️ Skipping {file.uid} due to LLM failure")
            self._advance(file, 'describe', 1 + len(method_lookup))
            self._advance(file, 'embed', 1 + len(method_lookup))
            return

        file.description = response.description
        self.embedder.enqueue(file)

        handled_indices = self._apply_description_map(response.description_map, method_lookup)

        if handled_indices:
            self._advance(file, 'describe', len(handled_indices))

        missed = len(method_lookup) - len(handled_indices)
        if missed > 0:
            self._advance(file, 'describe', missed)
            self._advance(file, 'embed', missed)

        logger.debug(f"Successfully Generated Description for file {file.uid}")

    async def _describe_class(self, cls: BaseClass):
        # Recurse on nested classes before describing this one
        non_methods = [c for c in cls.all_children if not isinstance(c, BaseMethod)]
        if non_methods:
            await asyncio.gather(*[self.describe(c) for c in non_methods])

        if cls.description:
            self._advance(cls, 'describe', 1 + len(cls.methods))
            self._handle_embed(cls)
            for m in cls.methods:
                if m.vector is not None:
                    self._advance(m, 'embed', 1)
                else:
                    self.embedder.enqueue(m)
            return

        logger.debug(f"Generating Description for class {cls.uid}...")

        method_lookup = {idx: m for idx, m in enumerate(cls.methods) if not m.description}

        already_described = [m for m in cls.methods if m.description]
        if already_described:
            self._advance(cls, 'describe', len(already_described))
            for m in already_described:
                if m.vector is not None:
                    self._advance(m, 'embed', 1)
                else:
                    self.embedder.enqueue(m)

        class ClassDescriptionSchema(BaseModel):
            description: str = Field(description="Description of the class")
            description_map: dict[str, str] = Field(default_factory=dict, description="Mapping of method_id to description")

        response = await self.llm.generate_description(
            input_data={
                "code": cls.skeletonize(),
                "method_ids_to_signatures": {str(idx): m.signature for idx, m in method_lookup.items()},
            },
            system_prompt=CLASS_SYSTEM_INSTRUCTION,
            response_schema=ClassDescriptionSchema,
        )

        if not response:
            logger.warning(f"⚠️ Skipping {cls.uid} due to LLM failure")
            self._advance(cls, 'describe', 1 + len(method_lookup))
            self._advance(cls, 'embed', 1 + len(method_lookup))
            return

        cls.description = response.description
        self.embedder.enqueue(cls)

        handled_indices = self._apply_description_map(response.description_map, method_lookup)

        if handled_indices:
            self._advance(cls, 'describe', len(handled_indices))

        missed = len(method_lookup) - len(handled_indices)
        if missed > 0:
            self._advance(cls, 'describe', missed)
            self._advance(cls, 'embed', missed)

        logger.debug(f"Successfully Generated Description for class {cls.uid}")

    def _describe_method(self, method: BaseMethod):
        # Methods are handled by their parent class/file batch call.
        # This handles the edge case of a directly-called method.
        self._advance(method, 'describe', 1)
        self._handle_embed(method)

    def _apply_description_map(self, description_map: dict, method_lookup: dict) -> set:
        """Applies LLM-returned descriptions to methods and enqueues them for embedding."""
        handled = set()
        for idx_str, desc in description_map.items():
            try:
                idx = int(idx_str)
            except (ValueError, TypeError):
                continue
            if idx in method_lookup:
                method_lookup[idx].description = desc
                handled.add(idx)
                self.embedder.enqueue(method_lookup[idx])
        return handled
