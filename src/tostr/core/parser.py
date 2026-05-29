from pathlib import Path
from abc import ABC
import asyncio
from loguru import logger

from tostr.core.models import BaseFile, Directory
from tostr.core.registry import Registry
from tostr.core.providers import StructBuilderProvider
from tostr.exceptions import LanguageNotSupportedError

class BaseParser(ABC):
    def __init__(self, project_dir: str, llm=None, registry: Registry=None):
        self.project_dir = project_dir
        self.llm = llm
        self.registry = registry
        # self.path_ignore = ["venv", ".venv", "env", ".env", "build", "dist", "__pycache__", ".tostr", ".git"]
    
    @property
    def files(self):
        if self._files: return self._files
        self._files = self.registry.uid_map.values().filter(lambda x: isinstance(x, BaseFile))
        return self._files
    
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
                # ROOT creation
                root_path = subpath
                if self.registry:
                    root_path = self.registry.relative_to_project(subpath)
                root = Directory(path=root_path, registry=self.registry)
                self.registry.root = root
                logger.debug(f"Created registry root: {root}")
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
                    if existing and isinstance(existing, Directory):
                        logger.debug(f"Using cached directory '{path}'")
                        root.add_child(existing)
                        self.parse_path(path, parent=existing)
                        continue

                    directory = Directory(path=relative_path, registry=self.registry, parent=root)
                    self.registry.add_struct(directory)
                    root.add_child(directory)
                    self.parse_path(path, parent=directory)
                else:
                    if existing and isinstance(existing, BaseFile):
                        if not self.registry.is_stale(existing):
                            logger.debug(f"Using cached file '{path}'")
                            root.add_child(existing)
                            continue

                    file = self.parse_file(path, parent=root)
                    if file:
                        self.registry.add_struct(file)
                        root.add_child(file)
        else:
            logger.debug(f"🔍 Parsing file '{subpath}'")
            file = self.parse_file(subpath)
            self.registry.root = file
            self.registry.add_struct(file)

    # @abstractmethod
    def parse_file(self, subpath: Path, parent: BaseStruct=None) -> BaseFile:
        logger.debug(f"Attempting to resolve builder for suffix {subpath.parts[-1]}")
        if self.registry.config.is_ignored(subpath):
            logger.debug(f"Skipping '{subpath}' due to path ignore rules")
            return None

        try:
            builder = StructBuilderProvider.get_builder(subpath.suffix, self.registry)
        except LanguageNotSupportedError as e:
            logger.warning(str(e))
            return None
        file_obj = builder.build_file().from_path(subpath, parent=parent)
        # logger.debug(json.dumps(file_obj.to_dict(), indent=2))
        return file_obj
    
    def resolve_dependencies(self):
        if self.registry.root:
            logger.info(f"Starting dependency resolution from root: {self.registry.root}")
            self.registry.root.resolve_dependencies()
    
    def load_cache(self):
        # print("Attempting to load cache from SQLite database...")
        # t_cache = time.time()
        self.registry.load_cache()
        # print(f"✅ Loaded Cache in {time.time() - t_cache:.2f} seconds")
                    
    async def resolve_descriptions_async(self):
        visited_ucids = set()
        coroutine_list = [file.resolve_description_async(self.llm, visited_ucids) for file in self.registry.files]
        if not coroutine_list:
            return
        await asyncio.gather(*coroutine_list)
