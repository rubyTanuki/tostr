from pathlib import Path
from abc import ABC
import asyncio
import hashlib
from loguru import logger

from tostr.core.models import BaseFile, Directory, BaseStruct
from tostr.core.registry import Registry
from tostr.core.providers import StructBuilderProvider
from tostr.exceptions import LanguageNotSupportedError

class BaseParser(ABC):
    def __init__(self, project_dir: str, llm=None, registry: Registry=None):
        self.project_dir = project_dir
        self.llm = llm
        self.registry = registry
    
    @property
    def files(self):
        return [x for x in self.registry.uid_map.values() if isinstance(x, BaseFile)]
    
    async def parse(self, subpath: Path = None):
        if not subpath:
            subpath = Path(self.project_dir)
        if not isinstance(subpath, Path):
            subpath = Path(subpath)

        self.parse_path(subpath)
        self.resolve_dependencies()
        await self.resolve_descriptions_async()
        
    def parse_path(self, subpath: Path, parent: Directory = None):
        if subpath.is_dir():
            logger.debug(f"🔍 Parsing directory '{subpath}'")
            
            if parent is None:
                root_path = subpath
                if self.registry:
                    root_path = self.registry.relative_to_project(subpath)
                root = Directory(path=root_path, registry=self.registry)
                self.registry.root = root
                self.registry.add_struct(root)
            else:
                root = parent

            for path in subpath.glob("*"):
                if self.registry.config.is_ignored(path):
                    logger.debug(f"Skipping '{path}' due to path ignore rules")
                    continue
                
                relative_path = self.registry.relative_to_project(path)
                existing = self.registry.get_struct_by_uid(str(relative_path))
                
                if path.is_dir():
                    directory = Directory(path=relative_path, registry=self.registry, parent=root)
                    self.registry.add_struct(directory)
                    root.add_child(directory)
                    self.parse_path(path, parent=directory)
                else:
                    file = self.parse_file(path, parent=root)
                    if file:
                        file.calculate_distributed_hash()
                        self.registry.add_struct(file)
                        root.add_child(file)
            
            root.calculate_distributed_hash()
        else:
            file = self.parse_file(subpath)
            if file:
                file.calculate_distributed_hash()
                self.registry.root = file
                self.registry.add_struct(file)

    def parse_file(self, subpath: Path, parent: BaseStruct=None) -> BaseFile:
        logger.debug(f"Attempting to resolve builder for suffix {subpath.suffix}")
        if self.registry.config.is_ignored(subpath):
            logger.debug(f"Skipping '{subpath}' due to path ignore rules")
            return None

        try:
            builder = StructBuilderProvider.get_builder(subpath.suffix, self.registry)
        except LanguageNotSupportedError as e:
            logger.warning(str(e))
            return None
        file_obj = builder.build_file().from_path(subpath, parent=parent)
        return file_obj
    
    def resolve_dependencies(self):
        if self.registry.root:
            logger.info(f"Starting dependency resolution from root: {self.registry.root}")
            self.registry.root.resolve_dependencies()
    
    def load_cache(self):
        self.registry.load_cache()
                    
    async def resolve_descriptions_async(self):
        visited_ucids = set()
        coroutine_list = [file.resolve_description_async(self.llm, visited_ucids) for file in self.registry.files]
        if not coroutine_list:
            return
        await asyncio.gather(*coroutine_list)
