from tree_sitter import Parser, Node, Query, QueryCursor
from pathlib import Path

from tostr.core.registry import Registry
from tostr.languages.java.language import JAVA_LANGUAGE
from tostr.core.builders import BaseBuilder, BaseFileBuilder, BaseClassBuilder, BaseMethodBuilder, BaseFieldBuilder
from tostr.languages.java.queries import DEPENDENCY_QUERY
from tostr.core.models import *

class JavaBuilder(BaseBuilder):
    
    def build_file(self) -> "JavaFileBuilder": 
        return JavaFileBuilder(self.registry)
    def build_class(self) -> "JavaClassBuilder": 
        return JavaClassBuilder(self.registry)
    def build_method(self) -> "JavaMethodBuilder": 
        return JavaMethodBuilder(self.registry)
    def build_field(self) -> "JavaFieldBuilder": 
        return JavaFieldBuilder(self.registry)
    
    
class JavaFileBuilder(BaseFileBuilder):
    def from_path(self, path: Path, parent: BaseStruct=None) -> BaseFile:
        file_obj = super().from_path(path)
    
        imports = []
        body_bytes = b""
        
        with open(path, "rb") as f:
            body_bytes = f.read()
        file_obj.body = body_bytes.decode("utf-8")
        
        parser = Parser(JAVA_LANGUAGE)
        tree = parser.parse(body_bytes)
        file_obj.node = tree.root_node
        
        # parse tree-sitter tree for children and imports
        class_builder = JavaClassBuilder(self.registry)
        method_builder = JavaMethodBuilder(self.registry)
        field_builder = JavaFieldBuilder(self.registry)
        enum_builder = JavaEnumBuilder(self.registry)
        for child in file_obj.node.children:
            if child.type == "package_declaration":
                for grandchild in child.children:
                    if grandchild.type in {"scoped_identifier", "identifier"}:
                        file_obj.package = grandchild.text.decode('utf-8')
                        break
                    
            if child.type == "import_declaration":
                for grandchild in child.children:
                    if grandchild.type in {"scoped_identifier", "identifier"}:
                        imports.append(grandchild.text.decode('utf-8'))
                        
            child_instance = None
            if child.type == "class_declaration" or child.type == "interface_declaration":
                child_instance = class_builder.from_node(child, parent=file_obj)
            elif child.type == "enum_declaration":
                child_instance = enum_builder.from_node(child, parent=file_obj)
            elif child.type == "method_declaration":
                child_instance = method_builder.from_node(child, parent=file_obj)
            elif child.type == "field_declaration":
                child_instance = field_builder.from_node(child, parent=file_obj)
            if child_instance:
                file_obj.add_child(child_instance)
                self.registry.add_struct(child_instance)
        
        file_obj.imports = imports
        
        return file_obj
        
        
class JavaClassBuilder(BaseClassBuilder):
    def from_node(self, node: Node, parent: BaseStruct=None) -> BaseClass:
        body = node.text.decode('utf-8')
        sig_parts = []
        name = ""
        
        # MODIFIERS
        for child in node.children:
            if child.type == 'modifiers':
                for mod_child in child.children:
                    if 'comment' not in mod_child.type:
                        sig_parts.append(mod_child.text.decode('utf-8').strip())
                break
        
        sig_parts.append("class")
        
        # NAME
        name_node = node.child_by_field_name('name')
        if name_node:
            name = name_node.text.decode('utf-8').strip()
            
        # TYPE PARAMETERS
        type_params_node = node.child_by_field_name('type_parameters')
        type_params_string = ""
        if type_params_node:
            type_params_string = type_params_node.text.decode('utf-8').strip()
        
        # INHERITS
        inherit_strings = []
        inherits_node = node.child_by_field_name('superclass')
        if inherits_node:
            identifier_node = inherits_node.named_children[0]
            inherit_strings.append(identifier_node.text.decode('utf-8').strip())
        interfaces_node = node.child_by_field_name('interfaces')
        if interfaces_node:
            type_list_node = interfaces_node.named_children[0]
            for type_node in type_list_node.named_children:
                inherit_strings.append(type_node.text.decode('utf-8').strip())
        
        # SIGNATURE
        sig_prefix = " ".join(sig_parts).replace('\n', ' ')
        signature = f"{sig_prefix} {name}{type_params_string}"
        
        uid = ""
        if isinstance(parent, BaseFile):
            uid = f"{parent.uid}#{name}"
        else:
            uid = f"{parent.uid}.{name}"
        
        instance = BaseClass(
           # BaseStruct
            name=name,
            uid=uid,
            registry=self.registry,
            parent=parent,
            path=parent.path if parent else None,
            
            # BaseCodeStruct
            signature=signature,
            body=body,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            node=node,
            
            # BaseClass
            inherits=inherit_strings,
        )
        
        # PARSE FOR CHILDREN
        class_builder = JavaClassBuilder(self.registry)
        method_builder = JavaMethodBuilder(self.registry)
        field_builder = JavaFieldBuilder(self.registry)
        enum_builder = JavaEnumBuilder(self.registry)
        
        body_node = node.child_by_field_name('body')
        if body_node:
            for child in body_node.children:
                child_instance = None
                if child.type == "class_declaration" or child.type == "interface_declaration":
                    child_instance = class_builder.from_node(child, parent=instance)
                elif child.type == "enum_declaration":
                    child_instance = enum_builder.from_node(child, parent=instance)
                elif child.type == "constructor_declaration":
                    child_instance = method_builder.from_node(child, parent=instance)
                elif child.type == "method_declaration":
                    child_instance = method_builder.from_node(child, parent=instance)
                elif child.type == "field_declaration":
                    child_instance = field_builder.from_node(child, parent=instance)
                if child_instance:
                    instance.add_child(child_instance)
                    self.registry.add_struct(child_instance)
            
        return instance
        
        

class JavaMethodBuilder(BaseMethodBuilder):
    def from_node(self, node: Node, parent: BaseStruct=None) -> BaseMethod:
        body = node.text.decode('utf-8')
        sig_parts = []
        name = ""
        
        # MODIFIERS
        for child in node.children:
            if child.type == 'modifiers':
                for mod_child in child.children:
                    if 'comment' not in mod_child.type:
                        sig_parts.append(mod_child.text.decode('utf-8').strip())
        
        # TYPE PARAMETERS
        type_params_node = node.child_by_field_name('type_parameters')
        if type_params_node:
            sig_parts.append(type_params_node.text.decode('utf-8').strip())
        
        # TYPE
        type_node = node.child_by_field_name('type')
        if type_node:
            sig_parts.append(type_node.text.decode('utf-8').strip())
        
        # NAME
        name_node = node.child_by_field_name('name')
        if name_node:
            name = name_node.text.decode('utf-8').strip()
        
        # PARAMETERS
        parameters = []
        params_node = node.child_by_field_name('parameters')
        if params_node:
            for param_child in params_node.named_children:
                if param_child.type == 'formal_parameter':
                    param_type_node = param_child.child_by_field_name('type')
                    if param_type_node:
                        parameters.append(param_type_node.text.decode('utf-8').strip())
            
        arity = len(parameters)
        parameters_string = f"({', '.join(parameters)})"
        
        # SIGNATURE
        sig_prefix = " ".join(sig_parts).replace('\n', ' ')
        signature = f"{sig_prefix} {name}{parameters_string}".strip()
        
        uid = ""
        if isinstance(parent, BaseFile):
            uid = f"{parent.uid}#{name}{parameters_string}"
        else:
            uid = f"{parent.uid}.{name}{parameters_string}"
        
        dependency_names = []
        
        query = Query(JAVA_LANGUAGE, DEPENDENCY_QUERY)
        cursor = QueryCursor(query)
        captures = cursor.captures(node)
        for dep in captures.get("dependencies", []):
            name = dep.child_by_field_name('name').text.decode('utf-8').strip()
            parameters = dep.child_by_field_name('arguments')
            arity = len(parameters.named_children)
            dependency_names.append((name, arity))
        
        return BaseMethod(
            # BaseStruct
            name=name,
            uid=uid,
            registry=self.registry,
            parent=parent,
            path=parent.path if parent else None,
            
            # BaseCodeStruct
            signature=signature,
            body=body,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            node=node,
            
            # BaseMethod
            arity=arity,
            dependency_names=dependency_names,
        )

class JavaFieldBuilder(BaseFieldBuilder):
    def from_node(self, node: Node, parent: BaseStruct=None) -> BaseField:
        body = node.text.decode('utf-8')
        sig_parts = []
        name = ""
        
        # MODIFIERS
        for child in node.children:
            if child.type == 'modifiers':
                for mod_child in child.children:
                    if 'comment' not in mod_child.type:
                        sig_parts.append(mod_child.text.decode('utf-8').strip())
        
        # TYPE
        type_node = node.child_by_field_name('type')
        field_type = type_node.text.decode('utf-8').strip() if type_node else ""
        if field_type:
            sig_parts.append(field_type)
        
        # NAME
        declarator_node = node.child_by_field_name('declarator')
        if declarator_node:
            name_node = declarator_node.child_by_field_name('name')
            if name_node:
                name = name_node.text.decode('utf-8').strip()
                sig_parts.append(name)
        
        signature = " ".join(sig_parts).replace('\n', ' ')
        
        uid = ""
        if isinstance(parent, BaseFile):
            uid = f"{parent.uid}#{name}"
        else:
            uid = f"{parent.uid}.{name}"

        return BaseField(
            # BaseStruct
            name=name,
            uid=uid,
            registry=self.registry,
            parent=parent,
            path=parent.path if parent else None,
            
            # BaseCodeStruct
            signature=signature,
            body=body,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            node=node,
            
            # BaseField
            field_type=field_type,
        )

class JavaEnumBuilder(JavaClassBuilder):
    def from_node(self, node: Node, parent: BaseStruct=None) -> BaseClass:
        # super().from_node(node, parent)
        return None
        # TODO: extract enum values and add them to enum_constants in a class