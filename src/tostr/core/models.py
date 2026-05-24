from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Set, List, Dict, Optional, TYPE_CHECKING, ClassVar
import json
import hashlib
from pathlib import Path

from loguru import logger
from tostr.core.providers import StructBuilderProvider
from tostr.exceptions import LanguageNotSupportedError

if TYPE_CHECKING:
    from tostr.core.registry import Registry

@dataclass(eq=False)
class BaseStruct(ABC):
    # IDENTITY
    name: str = ""              # exampleMethod
    uid: str = ""               # namespace.exampleClass#exampleMethod(num1: int) or src/com/example/Example.java
    id: str = field(init=False) # S-1a2b3c4d5e
    description: str = ""
    
    # DEPENDENCIES / GRAPH
    inbound_dependencies: Set[BaseStruct | str] = field(default_factory=set)
    inbound_dependencies_fuzzy: Set[BaseStruct | str] = field(default_factory=set) # for fuzzy matching during resolution
    outbound_dependencies: Set[BaseStruct | str] = field(default_factory=set)
    outbound_dependencies_fuzzy: Set[BaseStruct | str] = field(default_factory=set) # for fuzzy matching during resolution
    
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
    registry: "Registry" = None
    parent: BaseStruct | str = None
    children: Dict[str, Set[BaseStruct | str]] = field(default_factory=dict)
    path: Path = None
    
    _IDPREFIX: ClassVar[str] = "S"
    
    _all_children: List["BaseStruct"] = field(init=False, repr=False, default_factory=list)
    @property
    def all_children(self):
        if self._all_children: return self._all_children
        self._all_children = []
        for child_set in self.children.values():
            self._all_children.extend(child_set)
        return self._all_children
    
    @property
    def directories(self):
        return [child for child in self.all_children if isinstance(child, Directory)]
    
    @property
    def files(self):
        return list(self.children.get("BaseFile", set()))
    
    @property
    def methods(self):
        return [child for child in self.all_children if isinstance(child, BaseMethod)]
    
    @property
    def fields(self):
        return [child for child in self.all_children if isinstance(child, BaseField)]
    
    @property
    def classes(self):
        return [child for child in self.all_children if isinstance(child, BaseClass)]
    
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
        
        # for child_set in self.children.values():
        #     for child in child_set:
        #         edges.update(child.edges)
        #         edges.add((child.id, self.id, "contains"))
        
        return edges
    
    @property 
    def impact_score(self) -> int:
        return len(self.inbound_dependencies) + len(self.inbound_dependencies_fuzzy) + len(self.children)
    
    def __post_init__(self):
        id_hash = hashlib.md5(self.uid.encode('utf-8')).hexdigest()[:10]
        self.id = f"{self.__class__._IDPREFIX}-{id_hash}"
        
    def add_child(self, child: "BaseStruct"):
        type_name = child.__class__.__name__ # e.g., "BaseMethod"
        
        if type_name not in self.children:
            self.children[type_name] = set()
            
        self.children[type_name].add(child)
        child.set_parent(self)
    
    def set_parent(self, parent: "BaseStruct"):
        if self is parent:
            logger.warning(f"Attempted to set parent of {self} to itself. Skipping to avoid circular reference.")
            return
        self.parent = parent
    
    def add_dependency(self, target: "BaseStruct"):
        self.outbound_dependencies.add(target)
        self.outbound_dependency_names.add(target.uid)
        target.inbound_dependencies.add(self)
        target.inbound_dependency_names.add(self.uid)
        if isinstance(self.parent, BaseStruct) and isinstance(target.parent, BaseStruct):
            if self.parent != target.parent: 
                self.parent.add_dependency(target.parent)
                
    def add_fuzzy_dependency(self, target: "BaseStruct"):
        self.outbound_dependencies_fuzzy.add(target)
        self.outbound_dependency_names.add('~' + target.uid)
        target.inbound_dependencies_fuzzy.add(self)
        target.inbound_dependency_names.add('~' + self.uid)
        if isinstance(self.parent, BaseStruct) and isinstance(target.parent, BaseStruct):
            if self.parent != target.parent: 
                self.parent.add_fuzzy_dependency(target.parent)
        
    def resolve_dependencies(self):
        # logger.debug(f"Resolving dependencies for {self}")
        for child_set in self.children.values():
            for child in child_set:
                child.resolve_dependencies()
    
    @abstractmethod
    async def resolve_description_async(self, llm: "LLMClient", visited: set[str] = None):
        pass
    
    @classmethod
    def from_dict(cls, d: dict):
        data = d.copy()
        # REMOVE all init=False here
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
            "type": "BaseStruct",
            "path": str(self.path.resolve()),
            "description": self.description,
            "inbound_dependency_strings": self.inbound_dependency_strings,
            "outbound_dependency_strings": self.outbound_dependency_strings,
        }
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
    
    def __init__(self, path, registry=None, parent=None, uid=None):
        uid = uid or str(path)
        super().__init__(name=path.name, path=path, uid=uid, registry=registry, parent=parent)
    
    async def resolve_description_async(self, llm: "LLMClient", visited: set[str] = None):
        pass
    
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
                logger.debug(f"Skipping '{path}' due to path ignore rules")
                continue
            else:
                if path.is_dir():
                    logger.debug(f"🔍 Parsing directory '{path}'")
                    relative_path = self.registry.relative_to_project(path)
                    directory = Directory(path=relative_path, registry=self.registry, parent=self)
                    self.registry.add_struct(directory)
                    self.add_child(directory)
                    directory.parse_children()
                else:
                    logger.debug(f"Attempting to resolve builder for suffix {path.parts[-1]}")
                    try:
                        if self.registry.config.is_ignored(path):
                            logger.debug(f"Skipping '{path}' due to path ignore rules")
                            continue
                        builder = StructBuilderProvider.get_builder(path.suffix, self.registry)
                    except LanguageNotSupportedError as e:
                        continue
                    instance = builder.build_file().from_path(path, parent=self)
                    self.registry.add_struct(instance)
                    self.add_child(instance)
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "Directory"
        return data

@dataclass(eq=False)
class BaseFile(BaseStruct):
    _IDPREFIX: ClassVar[str] = "F"
    
    imports: List[str] = field(default_factory=list)
    package: str = ""
    body: str = ""
    node: "Node" = None
    
    async def resolve_description_async(self, llm: "LLMClient", visited: set[str] = None):
        for child in self.all_children:
            await child.resolve_description_async(llm, visited)
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "BaseFile"
        data["imports"] = self.imports
        data["body"] = self.body
        return data
    
@dataclass(eq=False) 
class BaseCodeStruct(BaseStruct):
    
    signature: str = ""         # public static int add(int num1, int num2) or class <T> Example extends BaseClass
    body: str = ""              # signature + method body or class body for hashing and LLM context
    diff_hash: str = ""         # hash of the code body - whitespace for change detection
    start_line: int = 0         
    end_line: int = 0
    node: "Node" = None         # Optional reference to the tree-sitter node for advanced processing (e.g., skeletonization)
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "BaseCodeStruct"
        data["signature"] = self.signature
        data["body"] = self.body
        data["diff_hash"] = self.diff_hash
        data["start_line"] = self.start_line
        data["end_line"] = self.end_line
        return data
    
@dataclass(eq=False)
class BaseClass(BaseCodeStruct):
    _IDPREFIX: ClassVar[str] = "C"
    enum_constants: Optional[List[str]] = None
    inherits: List[str] = field(default_factory=list) # list of parent class UIDs for inheritance relationships
    
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
    
    def resolve_dependencies(self):
        # logger.debug(f"Resolving dependencies for {self}")
        # resolve child dependencies
        super().resolve_dependencies()
        
        # resolve import dependencies
        for imp in self.imports:
            import_name = imp.split('.')[-1]
            import_dependency = self.registry.get_struct_by_uid(imp)
            if import_dependency:
                self.add_dependency(import_dependency)
        
        # resolve inheritance dependencies
        if self.inherits:
            for parent_class in self.inherits:
                parent_class_name = parent_class.split('.')[-1]
                parent_dependency = self.registry.get_struct_by_uid(parent_class_name)
                if parent_dependency:
                    self.add_dependency(parent_dependency)
        
        # logger.debug(f"Resolved dependencies for {self.name}: {self.outbound_dependency_strings}")

    def skeletonize(self) -> str:
        if not hasattr(self, 'node') or not self.node:
            raise ValueError("Node reference is required for skeletonization.")
        
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
            method_skeleton = tost.dump(child, verbosity=tost.VERBOSITY.SKELETON, pretty=False)
            skeleton_bytes = method_skeleton.encode('utf-8')
            result_bytes = result_bytes[:rel_start] + skeleton_bytes + result_bytes[rel_end:]
            
        return result_bytes.decode('utf-8')
    
    async def resolve_description_async(self, llm: "LLMClient", visited: set[str] = None):
        if visited is None: visited = set()
        
        if self.uid in visited or not self.needs_description:
            return
        visited.add(self.uid)
        
        if not self.registry:
            raise ValueError("Registry reference is required for description resolution.")
        try:
            response_obj = await llm.describe_class(self, self.imports)
        except Exception as e:
            logger.error(f"Failed to generate description for {self.uid}: {e}")
            return
            
        if not response_obj or response_obj.status == "error":
            error_msg = response_obj.error if response_obj else 'Returned None'
            logger.warning(f"⚠️ Skipping {self.uid} due to LLM failure: {error_msg}")
            return

        if response_obj.description:
            self.description = response_obj.description
        else:
            logger.warning(f"⚠️ Missing description for {self.uid} in LLM response")
            
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "BaseClass"
        if self.enum_constants:
            data["enum_constants"] = self.enum_constants
        data["inherits"] = self.inherits
        return data
    
@dataclass(eq=False)
class BaseMethod(BaseCodeStruct):
    _IDPREFIX: ClassVar[str] = "M"
    
    arity: int = 0
    dependency_names: Optional[List[tuple[str, int]]] = field(default_factory=list)
    
    children: dict = field(init=False, repr=False, default_factory=dict)
    
    # @abstractmethod
    # def _parse_dependencies(self):
    #     pass
    
    def resolve_dependencies(self):
        for name, arity in self.dependency_names:
            # LOCAL
            for child_set in self.children.values():
                for child in child_set:
                    if isinstance(child, BaseCodeStruct | BaseField) and child.name == name and child.arity == arity:
                        self.add_dependency(child)
                        break
            
            # IMPORTED
            for imp in self.parent.imports:
                import_name = f"{imp}#{name}"
                candidates = self.registry.resolve_methods(name=name, arity=arity, parent_name=import_name)
                if len(candidates) == 1:
                    self.add_dependency(candidates[0])
                elif len(candidates) > 1:
                    for c in candidates:
                        self.add_fuzzy_dependency(c)
            
            # INHERITED
            for parent_class in self.parent.inherits:
                parent_name = parent_class.split('.')[-1]
                # TODO: implement resolve_methods_by_name in registry
                candidates = self.registry.resolve_methods(name=name, arity=arity, parent_name=parent_name)
                if len(candidates) == 1:
                    self.add_dependency(candidates[0])
                elif len(candidates) > 1:
                    for c in candidates:
                        self.add_fuzzy_dependency(c)
            
    async def resolve_description_async(self, llm: "LLMClient", visited: set[str] = None):
        pass
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "BaseMethod"
        data["arity"] = self.arity
        return data

@dataclass(eq=False)
class BaseField(BaseCodeStruct):
    _IDPREFIX: ClassVar[str] = "V"
    
    field_type: str = ""
    children: dict = field(init=False, repr=False, default_factory=dict)
    
    def resolve_dependencies(self):
        pass
    
    async def resolve_description_async(self, llm: "LLMClient", visited: set[str] = None):
        pass
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["type"] = "BaseField"
        data["field_type"] = self.field_type
        return data