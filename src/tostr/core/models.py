from __future__ import annotations
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Set, List, Dict, Optional, TYPE_CHECKING, ClassVar
import json
import hashlib
from pathlib import Path
from pydantic import BaseModel, Field
import asyncio

from loguru import logger
from tostr.core.providers import StructBuilderProvider
from tostr.exceptions import LanguageNotSupportedError

from tostr.semantic.llm import CLASS_SYSTEM_INSTRUCTION, FILE_SYSTEM_INSTRUCTION, DIRECTORY_SYSTEM_INSTRUCTION


if TYPE_CHECKING:
    from tostr.core.registry import Registry

@dataclass(eq=False)
class BaseStruct(ABC):
    # IDENTITY
    name: str = ""              # exampleMethod
    uid: str = ""               # namespace.exampleClass#exampleMethod(num1: int) or src/com/example/Example.java
    id: str = field(init=False) # S-1a2b3c4d5e
    description: str = ""
    vector: Optional[List[float]] = None # populated asynchronously by the embedding client
    
    # DEPENDENCIES / GRAPH
    inbound_dependencies: Set[BaseStruct] = field(default_factory=set)
    inbound_dependencies_fuzzy: Set[BaseStruct] = field(default_factory=set) # for fuzzy matching during resolution
    outbound_dependencies: Set[BaseStruct] = field(default_factory=set)
    outbound_dependencies_fuzzy: Set[BaseStruct] = field(default_factory=set) # for fuzzy matching during resolution
    
    _inbound_dependency_strings: List[str] = field(default_factory=list)
    @property
    def inbound_dependency_strings(self):
        if not self._inbound_dependency_strings: self._inbound_dependency_strings = [f"{dep.id}|{dep.uid}" for dep in self.inbound_dependencies] + ['~'+f"{dep.id}|{dep.uid}" for dep in self.inbound_dependencies_fuzzy]
        return self._inbound_dependency_strings
    
    _outbound_dependency_strings: List[str] = field(default_factory=list)
    @property
    def outbound_dependency_strings(self):
        if not self._outbound_dependency_strings: self._outbound_dependency_strings = [f"{dep.id}|{dep.uid}" for dep in self.outbound_dependencies] + ['~'+f"{dep.id}|{dep.uid}" for dep in self.outbound_dependencies_fuzzy]
        return self._outbound_dependency_strings
    
    inbound_dependency_names: Set[str] = field(default_factory=set) # for serialization only, not used for resolution
    outbound_dependency_names: Set[str] = field(default_factory=set) # for serialization only, not used for resolution
    
    # CONTEXT
    registry: Registry = None
    parent: BaseStruct = None
    children: Dict[str, BaseStruct] = field(default_factory=dict)
    path: Path = None
    diff_hash: str = ""
    
    _IDPREFIX: ClassVar[str] = "S"

    # Caches
    _all_children_cache: Optional[List[BaseStruct]] = field(default=None, init=False, repr=False)
    _methods_cache: Optional[List[BaseMethod]] = field(default=None, init=False, repr=False)
    _fields_cache: Optional[List[BaseField]] = field(default=None, init=False, repr=False)
    _classes_cache: Optional[List[BaseClass]] = field(default=None, init=False, repr=False)
    _directories_cache: Optional[List[Directory]] = field(default=None, init=False, repr=False)
    
    @property
    def all_children(self):
        if self._all_children_cache is not None: return self._all_children_cache
        all_children = []
        for child_set in self.children.values():
            all_children.extend(child_set)
        self._all_children_cache = all_children
        return all_children
    
    @property
    def directories(self):
        if self._directories_cache is not None: return self._directories_cache
        self._directories_cache = [child for child in self.all_children if isinstance(child, Directory)]
        return self._directories_cache
    
    @property
    def files(self):
        return list(self.children.get("BaseFile", set()))
    
    @property
    def methods(self):
        if self._methods_cache is not None: return self._methods_cache
        self._methods_cache = [child for child in self.all_children if isinstance(child, BaseMethod)]
        return self._methods_cache
    
    @property
    def fields(self):
        if self._fields_cache is not None: return self._fields_cache
        self._fields_cache = [child for child in self.all_children if isinstance(child, BaseField)]
        return self._fields_cache
    
    @property
    def classes(self):
        if self._classes_cache is not None: return self._classes_cache
        self._classes_cache = [child for child in self.all_children if isinstance(child, BaseClass)]
        return self._classes_cache
    
    @property
    def edges(self):
        edges = set()
        for dependency in self.outbound_dependencies:
            edges.add((self.id, dependency.id, "depends_on"))
        for dependency in self.outbound_dependencies_fuzzy:
            edges.add((self.id, dependency.id, "depends_on_fuzzy"))
        
        if isinstance(self.parent, BaseStruct):
            edges.add((self.id, self.parent.id, "is_child_of"))
        elif isinstance(self.parent, str):
            edges.add((self.id, self.parent, "is_child_of"))
        
        return edges
    
    @property 
    def impact_score(self) -> int:
        return len(self.inbound_dependencies) + len(self.inbound_dependencies_fuzzy) + len(self.children)
    
    def __post_init__(self):
        id_hash = hashlib.md5(self.uid.encode('utf-8')).hexdigest()[:10]
        self.id = f"{self.__class__._IDPREFIX}-{id_hash}"
        
    def add_child(self, child: BaseStruct):
        type_name = child.__class__.__name__ # e.g., "BaseMethod"
        
        if type_name not in self.children:
            self.children[type_name] = set()
            
        self.children[type_name].add(child)
        child.set_parent(self)
        self._clear_caches()

    def _clear_caches(self):
        self._all_children_cache = None
        self._methods_cache = None
        self._fields_cache = None
        self._classes_cache = None
        self._directories_cache = None
    
    def set_parent(self, parent: BaseStruct):
        if self is parent:
            logger.warning(f"Attempted to set parent of {self} to itself. Skipping to avoid circular reference.")
            return
        self.parent = parent

    def calculate_distributed_hash(self):
        """Calculates diff_hash based on direct children's hashes."""
        if not self.all_children:
            return

        child_hashes = sorted([child.diff_hash for child in self.all_children if getattr(child, "diff_hash", None)])
        if child_hashes:
            self.diff_hash = hashlib.md5("".join(child_hashes).encode("utf-8")).hexdigest()
    
    def add_dependency(self, target: BaseStruct):
        self.outbound_dependencies.add(target)
        self.outbound_dependency_names.add(target.uid)
        target.inbound_dependencies.add(self)
        target.inbound_dependency_names.add(self.uid)
        if isinstance(self.parent, BaseStruct) and isinstance(target.parent, BaseStruct):
            if self.parent != target.parent: 
                self.parent.add_dependency(target.parent)
                
    def add_fuzzy_dependency(self, target: BaseStruct):
        self.outbound_dependencies_fuzzy.add(target)
        self.outbound_dependency_names.add('~' + target.uid)
        target.inbound_dependencies_fuzzy.add(self)
        target.inbound_dependency_names.add('~' + self.uid)
        if isinstance(self.parent, BaseStruct) and isinstance(target.parent, BaseStruct):
            if self.parent != target.parent: 
                self.parent.add_fuzzy_dependency(target.parent)
        
    def resolve_dependencies(self):
        # logger.debug(f"Resolving dependencies for {self}")
        for child_set in list(self.children.values()):
            for child in list(child_set):
                child.resolve_dependencies()
        
        if self.registry and self.registry.progress_tracker:
            self.registry.progress_tracker.advance('resolve', 1)

    @abstractmethod
    async def resolve_description_async(self, llm: LLMClient, embedder: EmbeddingClient = None):
        pass
    
    @classmethod
    def from_dict(cls, d: dict):
        data = d.copy()
        id = data.pop("id", None) 
        instance = cls(**data)
        if id:
            instance.id = id
        return instance
    
    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "uid": self.uid,
            "type": "struct",
            "path": str(self.path) if self.path else ".",
            "description": self.description,
            "diff_hash": self.diff_hash,
            "inbound_dependency_strings": self.inbound_dependency_strings,
            "outbound_dependency_strings": self.outbound_dependency_strings,
        }
        if self.vector is not None:
            data["vector"] = self.vector
        return data
    
    def to_json(self, indent=0):
        return json.dumps(self.to_dict(), indent=indent)
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if not isinstance(other, BaseStruct):
            return False
        return self.id == other.id
    
    def __str__(self):
        return f"<{self.__class__.__name__}: {self.uid}>"
    __repr__=__str__
    
@dataclass(eq=False)
class Directory(BaseStruct):
    _IDPREFIX: ClassVar[str] = "D"
    diff_hash: str = ""
    
    def __init__(self, path, registry=None, parent=None, uid=None):
        uid = uid or str(path)
        super().__init__(name=path.name, path=path, uid=uid, registry=registry, parent=parent)
    
    async def resolve_description_async(self, llm: LLMClient = None, embedder: EmbeddingClient = None):
        assert llm is not None, "LLMClient instance is required to resolve descriptions."
        
        if self.description:
            if self.registry and self.registry.progress_tracker:
                self.registry.progress_tracker.advance('describe', 1)
                if self.vector is not None:
                    self.registry.progress_tracker.advance('embed', 1)
                elif embedder:
                    embedder.enqueue(self)
            return

        if self.all_children:
            coroutine_list = [
                child.resolve_description_async(llm, embedder) 
                for child in self.all_children
            ]
            await asyncio.gather(*coroutine_list)

        if len(self.all_children) == 0:
            self.description = "Empty Directory"
            if self.registry and self.registry.progress_tracker:
                self.registry.progress_tracker.advance('describe', 1)
                self.registry.progress_tracker.advance('embed', 1)
            return
        if len(self.all_children) == 1:
            self.description = self.all_children[0].description
            if self.registry and self.registry.progress_tracker:
                self.registry.progress_tracker.advance('describe', 1)
                self.registry.progress_tracker.advance('embed', 1)
            return
        
        logger.debug(f"Generating Description for directory {self.uid}...")

        input_data = {
            c.uid: c.description for c in self.all_children
        }

        class DirectoryDescriptionSchema(BaseModel):
            description: str = Field(description="Description of the directory")

        response = await llm.generate_description(
            input_data=input_data,
            system_prompt=DIRECTORY_SYSTEM_INSTRUCTION,
            response_schema=DirectoryDescriptionSchema
        )

        if not response:
            logger.warning(f"⚠️ Skipping {self.uid} due to LLM failure")
            if self.registry and self.registry.progress_tracker:
                self.registry.progress_tracker.advance('embed', 1)
            return

        self.description = response.description

        if embedder is not None:
            embedder.enqueue(self)

        logger.debug(f"Successfully Generated Description for directory {self.uid}")
    
    def parse_children(self):
        if self.path is None:
            logger.error(f"{self} has no path")
            return
        
        # Ensure we use an absolute path for globbing if it's relative
        full_path = self.path
        if not full_path.is_absolute() and self.registry:
            full_path = self.registry.project_path / self.path

        for path in full_path.glob("*"):
            if self.registry.config.is_ignored(path):
                logger.debug(f"Skipping \'{path}\' due to path ignore rules")
                continue
            else:
                if path.is_dir():
                    logger.debug(f"🔍 Parsing directory \'{path}\'")
                    relative_path = self.registry.relative_to_project(path)
                    directory = Directory(path=relative_path, registry=self.registry, parent=self)
                    self.registry.add_struct(directory)
                    self.add_child(directory)
                    directory.parse_children()
                else:
                    logger.debug(f"Attempting to resolve builder for suffix {path.parts[-1]}")
                    try:
                        if self.registry.config.is_ignored(path):
                            logger.debug(f"Skipping \'{path}\' due to path ignore rules")
                            continue
                        builder = StructBuilderProvider.get_builder(path.suffix, self.registry)
                    except LanguageNotSupportedError as e:
                        continue
                    instance = builder.build_file().from_path(path, parent=self)
                    
                    # Calculate file hash from children if any exist
                    instance.calculate_distributed_hash()

                    self.registry.add_struct(instance)
                    self.add_child(instance)
        
        # Calculate directory hash from its direct children
        self.calculate_distributed_hash()
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "directory"
        data["diff_hash"] = self.diff_hash
        return data

@dataclass(eq=False)
class BaseFile(BaseStruct):
    _IDPREFIX: ClassVar[str] = "F"
    
    imports: List[str] = field(default_factory=list)
    package: str = ""
    body: str = ""
    diff_hash: str = ""
    node: "Node" = None
    
    async def resolve_description_async(self, llm: LLMClient, embedder: EmbeddingClient = None):
        assert llm is not None, "LLMClient instance is required to resolve descriptions."
        
        if self.description:
            if self.registry and self.registry.progress_tracker:
                self.registry.progress_tracker.advance('describe', 1)
                if self.vector is not None:
                    self.registry.progress_tracker.advance('embed', 1)
                elif embedder:
                    embedder.enqueue(self)
            return

        if self.all_children:
            coroutine_list = [
                child.resolve_description_async(llm, embedder) 
                for child in self.all_children
            ]
            await asyncio.gather(*coroutine_list)

        if len(self.all_children) == 0:
            self.description = "Empty File"
            if self.registry and self.registry.progress_tracker:
                self.registry.progress_tracker.advance('describe', 1)
                self.registry.progress_tracker.advance('embed', 1)
            return
        if len(self.all_children) == 1:
            self.description = self.all_children[0].description
            self.vector = self.all_children[0].vector
            if self.registry and self.registry.progress_tracker:
                self.registry.progress_tracker.advance('describe', 1)
                self.registry.progress_tracker.advance('embed', 1)
            return
        
        logger.debug(f"Generating Description for file {self.uid}...")

        input_data = {
            c.uid: c.description for c in self.all_children
        }

        class FileDescriptionSchema(BaseModel):
            description: str = Field(description="Description of the file")

        response = await llm.generate_description(
            input_data=input_data,
            system_prompt=FILE_SYSTEM_INSTRUCTION,
            response_schema=FileDescriptionSchema
        )

        if not response:
            logger.warning(f"⚠️ Skipping {self.uid} due to LLM failure")
            if self.registry and self.registry.progress_tracker:
                self.registry.progress_tracker.advance('embed', 1)
            return

        self.description = response.description

        if embedder is not None:
            embedder.enqueue(self)

        logger.debug(f"Successfully Generated Description for file {self.uid}")


    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "file"
        data["imports"] = self.imports
        data["body"] = self.body
        data["diff_hash"] = self.diff_hash
        return data

@dataclass(eq=False) 
class BaseCodeStruct(BaseStruct):
    
    signature: str = ""         # public static int add(int num1, int num2) or class <T> Example extends BaseClass
    body: str = ""              # signature + method body or class body for hashing and LLM context
    start_line: int = 0         
    end_line: int = 0
    node: Node = None         # Optional reference to the tree-sitter node for advanced processing (e.g., skeletonization)
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "codestruct"
        data["signature"] = self.signature
        data["body"] = self.body
        data["start_line"] = self.start_line
        data["end_line"] = self.end_line
        return data
    
@dataclass(eq=False)
class BaseClass(BaseCodeStruct):
    _IDPREFIX: ClassVar[str] = "C"
    enum_constants: Optional[List[str]] = None
    inherits: List[str] = field(default_factory=list) # list of parent class UIDs for inheritance relationships
    
    _type_cache: Dict[str, Optional[BaseStruct]] = field(default_factory=dict, init=False, repr=False)
    _potential_parents_cache: Optional[List[str]] = field(default=None, init=False, repr=False)

    def _clear_caches(self):
        super()._clear_caches()
        self._type_cache = {}
        self._potential_parents_cache = None

    @property
    def needs_description(self) -> bool:
        if not self.description:
            return True
        for child_set in self.children.values():
            for child in child_set:
                if not child.description and not isinstance(child, BaseField):
                    return True
        return False

    @property
    def imports(self) -> List[str]:
        return self.parent.imports
    
    def resolve_type(self, type_name: str) -> Optional[BaseStruct]:
        """Resolves a simple or scoped type name to a struct using package and imports."""
        if not type_name: return None
        if type_name in self._type_cache:
            return self._type_cache[type_name]

        # 1. Exact match (already a UID)
        dep = self.registry.get_struct_by_uid(type_name)
        
        # 2. Same package
        if not dep:
            package = getattr(self.parent, "package", None) if isinstance(self.parent, BaseFile) else None
            if package:
                dep = self.registry.get_struct_by_uid(f"{package}.{type_name}")
        
        # 3. Specific imports
        if not dep:
            for imp in self.imports:
                if imp.endswith(f".{type_name}"):
                    dep = self.registry.get_struct_by_uid(imp)
                    if dep: break
        
        # 4. Wildcard imports
        if not dep:
            for imp in self.imports:
                if imp.endswith(".*"):
                    package_name = imp[:-2]
                    dep = self.registry.get_struct_by_uid(f"{package_name}.{type_name}")
                    if dep: break
        
        self._type_cache[type_name] = dep
        return dep

    def resolve_dependencies(self):
        # logger.debug(f"Resolving dependencies for {self}")
        # resolve child dependencies
        super().resolve_dependencies()
        
        # resolve import dependencies
        for imp in self.imports:
            if not imp.endswith(".*"):
                import_dependency = self.registry.get_struct_by_uid(imp)
                if import_dependency:
                    self.add_dependency(import_dependency)
        
        # resolve inheritance dependencies
        if self.inherits:
            for parent_class in self.inherits:
                dep = self.resolve_type(parent_class)
                if dep:
                    self.add_dependency(dep)
        
        # resolve field types
        for field in self.fields:
            dep = self.resolve_type(field.field_type)
            if dep:
                self.add_dependency(dep)
        
        # logger.debug(f"Resolved dependencies for {self.name}: {self.outbound_dependency_strings}")

    def skeletonize(self) -> str:
        if not hasattr(self, 'node') or not self.node:
            raise ValueError("Node reference is required for skeletonization.")
        
        from tostr.core.serializer import tost, Verbosity

        result_bytes = self.node.text
        start_byte = self.node.start_byte
        
        children_to_replace = []
        for child_set in self.children.values():
            if child_set and isinstance(next(iter(child_set)), BaseCodeStruct):
                children_to_replace.extend(child_set)
        children_to_replace.sort(key=lambda x: x.node.start_byte, reverse=True)
        
        for child in children_to_replace:
            if not child.description:
                continue
            
            rel_start = child.node.start_byte - start_byte
            rel_end = child.node.end_byte - start_byte
            method_skeleton = tost.dump(child, verbosity=Verbosity.SKELETON, pretty=False)
            skeleton_bytes = method_skeleton.encode('utf-8')
            result_bytes = result_bytes[:rel_start] + skeleton_bytes + result_bytes[rel_end:]
            
        return result_bytes.decode('utf-8')
    
    async def resolve_description_async(self, llm: LLMClient, embedder: EmbeddingClient = None):
        assert llm is not None, "LLMClient instance is required to resolve descriptions."
        
        # 1. Handle Children Recursion (e.g., nested classes)
        if self.all_children:
            coroutine_list = [
                child.resolve_description_async(llm, embedder) 
                for child in self.all_children
                if not isinstance(child, BaseMethod) # Methods are handled by this class below
            ]
            if coroutine_list:
                await asyncio.gather(*coroutine_list)

        # 2. If already described, account for ourselves and our methods and exit
        if self.description:
            if self.registry and self.registry.progress_tracker:
                self.registry.progress_tracker.advance('describe', 1 + len(self.methods))
                if self.vector is not None:
                    self.registry.progress_tracker.advance('embed', 1)
                elif embedder:
                    embedder.enqueue(self)
                
                for m in self.methods:
                    if m.vector is not None:
                        self.registry.progress_tracker.advance('embed', 1)
                    elif embedder:
                        embedder.enqueue(m)
            return

        # 3. Process this class and its methods
        logger.debug(f"Generating Description for class {self.uid}...")

        method_lookup = {idx: m for idx, m in enumerate(self.methods) if m.description is None}
        
        # Account for methods that already have descriptions
        already_described = [m for m in self.methods if m.description is not None]
        if self.registry and self.registry.progress_tracker and already_described:
            self.registry.progress_tracker.advance('describe', len(already_described))
            for m in already_described:
                if m.vector is not None:
                    self.registry.progress_tracker.advance('embed', 1)
                elif embedder:
                    embedder.enqueue(m)

        input_data = {
            "code": self.skeletonize(),
            "method_ids_to_signatures": {idx: m.signature for idx, m in method_lookup.items()}
        }

        class ClassDescriptionSchema(BaseModel):
            description: str = Field(description="Description of the class")
            description_map: dict[int, str] = Field(default_factory=dict, description="Mapping of method_id to method")

        response = await llm.generate_description(
            input_data=input_data,
            system_prompt=CLASS_SYSTEM_INSTRUCTION,
            response_schema=ClassDescriptionSchema
        )

        if not response:
            logger.warning(f"⚠️ Skipping {self.uid} due to LLM failure")
            if self.registry and self.registry.progress_tracker:
                self.registry.progress_tracker.advance('describe', 1 + len(method_lookup))
                self.registry.progress_tracker.advance('embed', 1 + len(method_lookup))
            return

        self.description = response.description

        if embedder is not None:
            embedder.enqueue(self)

        handled_indices = set()
        for idx, desc in response.description_map.items():
            if idx in method_lookup:
                method = method_lookup[idx]
                method.description = desc
                handled_indices.add(idx)
                if embedder is not None:
                    embedder.enqueue(method)

        # Handle any methods that were sent but not described by the LLM
        missed_count = len(method_lookup) - len(handled_indices)
        if missed_count > 0 and self.registry and self.registry.progress_tracker:
            self.registry.progress_tracker.advance('describe', missed_count)
            self.registry.progress_tracker.advance('embed', missed_count)

        logger.debug(f"Successfully Generated Description for class {self.uid}")
            
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "class"
        if self.enum_constants:
            data["enum_constants"] = self.enum_constants
        data["inherits"] = self.inherits
        return data
    
@dataclass(eq=False)
class BaseMethod(BaseCodeStruct):
    _IDPREFIX: ClassVar[str] = "M"
    
    arity: int = 0
    # List of (name, arity, receiver, is_creation)
    dependency_names: Optional[List[tuple]] = field(default_factory=list)
    
    children: dict = field(init=False, repr=False, default_factory=dict)
    
    # @abstractmethod
    # def _parse_dependencies(self):
    #     pass

    async def resolve_description_async(self, llm: LLMClient, embedder: EmbeddingClient = None):
        # Methods are usually handled by their parent class, but we handle direct calls for robustness.
        if self.registry and self.registry.progress_tracker:
            self.registry.progress_tracker.advance('describe', 1)
            if self.vector is not None:
                self.registry.progress_tracker.advance('embed', 1)
            elif embedder:
                embedder.enqueue(self)
    
    def resolve_dependencies(self):
        logger.debug(f"Resolving dependencies for method {self.uid}")
        for dep_info in self.dependency_names:
            # Handle both old (name, arity) and new (name, arity, receiver, is_creation) formats
            if len(dep_info) == 2:
                name, arity = dep_info
                receiver, is_creation = None, False
            else:
                name, arity, receiver, is_creation = dep_info

            if is_creation:
                if isinstance(self.parent, BaseClass):
                    dep = self.parent.resolve_type(name)
                    if dep: self.add_dependency(dep)
                continue

            # --- METHOD RESOLUTION ---
            resolved = False
            # 1. LOCAL
            search_scope = self.parent.children if self.parent else self.children
            for child_set in list(search_scope.values()):
                for child in list(child_set):
                    if child.name == name and getattr(child, "arity", -1) == arity:
                        self.add_dependency(child)
                        resolved = True
                        break
                if resolved: break
            if resolved: continue

            # 2. RECEIVER-BASED HEURISTIC
            if receiver and isinstance(self.parent, BaseClass):
                # Check fields for receiver type
                receiver_type = None
                for field in self.parent.fields:
                    if field.name == receiver:
                        receiver_type = field.field_type
                        break
                
                if receiver_type:
                    dep_type = self.parent.resolve_type(receiver_type)
                    if dep_type:
                        candidates = self.registry.resolve_methods(name=name, arity=arity, parent_name=dep_type.uid)
                        if candidates:
                            self.add_dependency(candidates[0])
                            continue
            
            # 3. IMPORTED & INHERITED (including wildcards)
            if isinstance(self.parent, BaseClass):
                if self.parent._potential_parents_cache is None:
                    potential_parents = []
                    # Same package
                    package = getattr(self.parent.parent, "package", None) if isinstance(self.parent.parent, BaseFile) else None
                    if package: potential_parents.append(f"{package}.*")
                    
                    # All imports
                    potential_parents.extend(self.parent.imports)
                    
                    # All inheritance
                    potential_parents.extend(self.parent.inherits)
                    self.parent._potential_parents_cache = potential_parents
                
                potential_parents = self.parent._potential_parents_cache
                all_candidates = []
                for p_name in potential_parents:
                    candidates = self.registry.resolve_methods(name=name, arity=arity, parent_name=p_name)
                    all_candidates.extend(candidates)
                
                if len(all_candidates) == 1:
                    # logger.debug(f"Resolved {name} to {all_candidates[0].uid}")
                    self.add_dependency(all_candidates[0])
                elif len(all_candidates) > 1:
                    # Apply heuristic: if receiver matches part of class name
                    refined_candidates = []
                    if receiver:
                        for c in all_candidates:
                            if receiver.lower() in c.parent.name.lower():
                                refined_candidates.append(c)
                    
                    if len(refined_candidates) == 1:
                        self.add_dependency(refined_candidates[0])
                    else:
                        for c in all_candidates:
                            self.add_fuzzy_dependency(c)
        
        if self.registry and self.registry.progress_tracker:
            self.registry.progress_tracker.advance('resolve', 1)

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "method"
        data["arity"] = self.arity
        data["dependency_names"] = self.dependency_names
        return data

@dataclass(eq=False)
class BaseField(BaseCodeStruct):
    _IDPREFIX: ClassVar[str] = "V"
    
    field_type: str = ""
    children: dict = field(init=False, repr=False, default_factory=dict)

    # @abstractmethod
    # def _parse_dependencies(self):
    #     pass

    async def resolve_description_async(self, llm: LLMClient, embedder: EmbeddingClient = None):
        pass
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "field"
        data["field_type"] = self.field_type
        return data