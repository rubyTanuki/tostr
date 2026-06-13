from __future__ import annotations
from tree_sitter import Parser, Node, Query, QueryCursor
from pathlib import Path
import hashlib
import re

from tostr.core.registry import Registry
from tostr.languages.python.language import PYTHON_LANGUAGE
from tostr.core.builders import BaseBuilder, BaseFileBuilder, BaseClassBuilder, BaseMethodBuilder, BaseFieldBuilder
from tostr.languages.python.queries import DEPENDENCY_QUERY
from tostr.core.models import *

class PythonBuilder(BaseBuilder):
    def handles_extension(self, ext: str) -> bool:
        return ext.lower() == ".py"

    def build_file(self) -> PythonFileBuilder: 
        return PythonFileBuilder(self.registry)
    def build_class(self) -> PythonClassBuilder: 
        return PythonClassBuilder(self.registry)
    def build_method(self) -> PythonMethodBuilder: 
        return PythonMethodBuilder(self.registry)
    def build_field(self) -> PythonFieldBuilder: 
        return PythonFieldBuilder(self.registry)

class PythonFileBuilder(BaseFileBuilder):
    def from_path(self, path: Path, parent: BaseStruct=None) -> BaseFile:
        file_obj = super().from_path(path)

        body_bytes = b""
        with open(path, "rb") as f:
            body_bytes = f.read()
        file_obj.body = body_bytes.decode("utf-8")
        file_obj.diff_hash = hashlib.md5(body_bytes).hexdigest()

        parser = Parser(PYTHON_LANGUAGE)
        tree = parser.parse(body_bytes)
        file_obj.node = tree.root_node

        # UID stays the relative filepath (set by BaseFileBuilder.from_path) so all
        # children are prefix-matchable. The dotted module path is the *logical* name,
        # stored on `package` and resolved through Registry's logical-name lookup.
        rel_path = self.registry.relative_to_project(path)
        module_path = ".".join(rel_path.with_suffix("").parts).replace("/", ".").replace("\\", ".")
        file_obj.package = module_path

        # Phase 1: Parse imports first to build alias_map before children are parsed.
        # alias_map: {alias_name -> original_uid} used to normalize call-site names.
        imports = []
        alias_map = {}
        for child in file_obj.node.children:
            if child.type == "import_statement":
                for name_child in child.children_by_field_name("name"):
                    if name_child.type == "aliased_import":
                        original_node = name_child.child_by_field_name("name")
                        alias_node = name_child.child_by_field_name("alias")
                        if original_node:
                            original = original_node.text.decode('utf-8')
                            imports.append(original)
                            if alias_node:
                                alias_map[alias_node.text.decode('utf-8')] = original
                    else:
                        imports.append(name_child.text.decode('utf-8'))

            elif child.type == "import_from_statement":
                module_name = ""
                module_node = child.child_by_field_name("module_name")
                relative_import_node = child.child_by_field_name("relative_import")

                if module_node:
                    raw = module_node.text.decode('utf-8')
                    if raw.startswith('.'):
                        # Relative import: ".models" or "..base" — resolve against current package.
                        stripped = raw.lstrip('.')
                        num_dots = len(raw) - len(stripped)
                        if file_obj.package:
                            parts = file_obj.package.split('.')
                            base_parts = parts[:-num_dots] if num_dots <= len(parts) else []
                            module_name = ".".join(base_parts + ([stripped] if stripped else []))
                        else:
                            module_name = stripped
                    else:
                        module_name = raw
                elif relative_import_node:
                    prefix_node = relative_import_node.child_by_field_name("prefix")
                    dotted_name_node = relative_import_node.child_by_field_name("name")
                    dots = prefix_node.text.decode('utf-8') if prefix_node else ""
                    dotted_part = dotted_name_node.text.decode('utf-8') if dotted_name_node else ""
                    num_dots = dots.count('.')
                    if num_dots > 0 and file_obj.package:
                        parts = file_obj.package.split('.')
                        base_parts = parts[:-num_dots] if num_dots <= len(parts) else []
                        module_name = ".".join(base_parts + ([dotted_part] if dotted_part else []))
                    else:
                        module_name = dotted_part

                if module_name:
                    has_wildcard = any(gc.type == "wildcard_import" for gc in child.children)
                    if has_wildcard:
                        imports.append(f"{module_name}.*")
                    else:
                        for gc in child.named_children:
                            if gc.type in {"aliased_import", "dotted_name", "identifier"}:
                                if gc == module_node or gc == relative_import_node:
                                    continue
                                if gc.type == "aliased_import":
                                    name_node = gc.child_by_field_name("name") or gc
                                    alias_node = gc.child_by_field_name("alias")
                                    imp_name = name_node.text.decode('utf-8')
                                    original_uid = f"{module_name}.{imp_name}"
                                    imports.append(original_uid)
                                    if alias_node:
                                        alias_map[alias_node.text.decode('utf-8')] = original_uid
                                else:
                                    imports.append(f"{module_name}.{gc.text.decode('utf-8')}")

        file_obj.imports = list(set(imports))

        # Phase 2: Parse children (methods capture raw call-site names/receivers).
        self._parse_children(file_obj.node, file_obj)

        # Phase 3: Normalize aliases in all descendant method dependency_names.
        if alias_map:
            self._normalize_deps(file_obj, alias_map)

        return file_obj

    def _normalize_deps(self, struct: "BaseStruct", alias_map: dict):
        """Post-process all method dependency_names, replacing alias names with original UIDs."""
        for child_set in struct.children.values():
            for child in child_set:
                if isinstance(child, BaseMethod) and child.dependency_names:
                    child.dependency_names = [
                        (
                            alias_map.get(name, name),
                            arity,
                            alias_map.get(receiver, receiver) if receiver else receiver,
                            is_creation,
                        )
                        for name, arity, receiver, is_creation in child.dependency_names
                    ]
                self._normalize_deps(child, alias_map)

    def _parse_children(self, node: Node, parent: BaseStruct):
        class_builder = PythonClassBuilder(self.registry)
        method_builder = PythonMethodBuilder(self.registry)
        field_builder = PythonFieldBuilder(self.registry)

        for child in node.children:
            child_instance = None
            if child.type == "class_definition":
                child_instance = class_builder.from_node(child, parent=parent)
            elif child.type == "function_definition":
                child_instance = method_builder.from_node(child, parent=parent)
            elif child.type == "decorated_definition":
                for grandchild in child.children:
                    if grandchild.type == "class_definition":
                        child_instance = class_builder.from_node(grandchild, parent=parent)
                        break
                    elif grandchild.type == "function_definition":
                        child_instance = method_builder.from_node(grandchild, parent=parent)
                        break
            elif child.type == "expression_statement":
                # Check for assignments
                assignment = None
                if child.named_children and child.named_children[0].type == "assignment":
                    assignment = child.named_children[0]
                if assignment:
                    child_instance = field_builder.from_node(child, parent=parent)
            
            if child_instance:
                parent.add_child(child_instance)
                self.registry.add_struct(child_instance)

class PythonClassBuilder(BaseClassBuilder):
    def from_node(self, node: Node, parent: BaseStruct=None) -> BaseClass:
        body = node.text.decode('utf-8')
        name = ""
        
        # NAME
        name_node = node.child_by_field_name('name')
        if name_node:
            name = name_node.text.decode('utf-8').strip()
            
        # INHERITS
        inherit_strings = []
        superclasses_node = node.child_by_field_name('superclasses')
        if superclasses_node:
            for arg in superclasses_node.named_children:
                inherit_strings.append(arg.text.decode('utf-8').strip())
        
        # SIGNATURE
        signature = f"class {name}"
        if inherit_strings:
            signature += f"({', '.join(inherit_strings)})"
        
        uid = ""
        if isinstance(parent, BaseFile):
            uid = f"{parent.uid}#{name}"
        elif parent:
            uid = f"{parent.uid}.{name}"
        else:
            uid = name

        instance = BaseClass(
            name=name,
            uid=uid,
            registry=self.registry,
            parent=parent,
            path=parent.path if parent else None,
            signature=signature,
            body=body,
            diff_hash=hashlib.md5(node.text).hexdigest(),
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            node=node,
            inherits=inherit_strings,
        )
        
        # PARSE FOR CHILDREN
        body_node = node.child_by_field_name('body')
        if body_node:
            PythonFileBuilder(self.registry)._parse_children(body_node, instance)
            
        return instance

class PythonMethodBuilder(BaseMethodBuilder):
    def from_node(self, node: Node, parent: BaseStruct=None) -> BaseMethod:
        body = node.text.decode('utf-8')
        name = ""
        
        # NAME
        name_node = node.child_by_field_name('name')
        if name_node:
            name = name_node.text.decode('utf-8').strip()
        
        # PARAMETERS
        parameters = []
        params_node = node.child_by_field_name('parameters')
        if params_node:
            for param in params_node.named_children:
                # In Python, we just care about the number of parameters for arity
                param_text = param.text.decode('utf-8').strip()
                # Collapse whitespace/newlines and truncate long default values
                param_text = re.sub(r'\s+', ' ', param_text)
                if len(param_text) > 50:
                    param_text = param_text[:47] + "..."
                parameters.append(param_text)
            
        # Exclude self/cls from arity — callers never pass them.
        first_bare = parameters[0].split('=')[0].split(':')[0].strip() if parameters else ""
        arity_params = parameters[1:] if first_bare in ('self', 'cls') else parameters
        arity = len(arity_params)
        parameters_string = f"({', '.join(parameters)})"
        
        # SIGNATURE
        signature = f"def {name}{parameters_string}"
        
        uid = ""
        if isinstance(parent, BaseFile):
            uid = f"{parent.uid}#{name}{parameters_string}"
        elif parent:
            uid = f"{parent.uid}.{name}{parameters_string}"
        else:
            uid = f"{name}{parameters_string}"

        dependency_names = []
        query = Query(PYTHON_LANGUAGE, DEPENDENCY_QUERY)
        cursor = QueryCursor(query)
        matches = cursor.matches(node)
        for _, captures in matches:
            if "method_call" in captures:
                name_node = captures.get("name")[0]
                dep_name = name_node.text.decode('utf-8').strip()
                args_node = captures.get("args")[0]
                dep_arity = len(args_node.named_children)
                receiver = captures.get("receiver")[0].text.decode('utf-8').strip() if "receiver" in captures else None
                
                # In Python, we don't know if it's object creation or method call.
                # We'll mark is_creation=False and let resolver try both.
                dependency_names.append((dep_name, dep_arity, receiver, False))
        
        return BaseMethod(
            name=name,
            uid=uid,
            registry=self.registry,
            parent=parent,
            path=parent.path if parent else None,
            signature=signature,
            body=body,
            diff_hash=hashlib.md5(node.text).hexdigest(),
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            node=node,
            arity=arity,
            dependency_names=dependency_names,
        )

class PythonFieldBuilder(BaseFieldBuilder):
    def from_node(self, node: Node, parent: BaseStruct=None) -> BaseField:
        # node is typically an expression_statement containing an assignment
        body = node.text.decode('utf-8')
        name = ""
        field_type = ""
        
        assignment = None
        if node.type == "expression_statement" and node.named_children and node.named_children[0].type == "assignment":
             assignment = node.named_children[0]
        elif node.type == "assignment":
             assignment = node
             
        if assignment:
            left_node = assignment.child_by_field_name('left') or (assignment.named_children[0] if assignment.named_children else None)
            if left_node:
                name = left_node.text.decode('utf-8').strip()
            
            type_node = assignment.child_by_field_name('type')
            if type_node:
                field_type = type_node.text.decode('utf-8').strip()
        
        signature = f"{name}"
        if field_type:
            signature = f"{name}: {field_type}"
            
        uid = ""
        if isinstance(parent, BaseFile):
            uid = f"{parent.uid}#{name}"
        elif parent:
            uid = f"{parent.uid}.{name}"
        else:
            uid = name

        return BaseField(
            name=name,
            uid=uid,
            registry=self.registry,
            parent=parent,
            path=parent.path if parent else None,
            signature=signature,
            body=body,
            diff_hash=hashlib.md5(node.text).hexdigest(),
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            node=node,
            field_type=field_type,
        )
