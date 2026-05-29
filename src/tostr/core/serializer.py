from tostr.core.models import *

from enum import IntEnum
from loguru import logger

import textwrap

_INDENT_TAB = "  "

_LINE_WRAP_WIDTH = 120

class Verbosity(IntEnum):
    HEADER = 0
    SKELETON = 1
    VERBOSE = 2
    FULL = 3

class tost:
    
    @classmethod
    def dump_skeleton(
        cls, 
        obj: "BaseStruct",
        files_only: bool = True,
        depth: int = 7,
        # indent: int = 0,
        pretty: bool = True
    ) -> str:
        indent_str = _INDENT_TAB if pretty else ""
        parts = []
        
        header_str = f"{obj.id} | {obj.uid}"
        parts.append(header_str)
        
        if obj.files:
            if depth == 0:
                parts.append(f"{indent_str}... ({len(obj.files)} files)")
            else:
                for f in obj.files:
                    parts.append(cls.dump_skeleton(f, files_only=files_only, depth=depth-1, pretty=pretty))
        if obj.directories:
            if depth == 0:
                parts.append(f"{indent_str}... ({len(obj.directories)} directories)")
            else:
                for d in obj.directories:
                    if d is obj:
                        logger.warning(f"Skipping dumping directory {d} as it is the same as its parent {obj}, likely to avoid circular reference.")
                        continue
                    parts.append(cls.dump_skeleton(d, files_only=files_only, depth=depth-1, pretty=pretty))
        if obj.classes and not files_only:
            if depth == 0:
                parts.append(f"{indent_str}... ({len(obj.classes)} classes)")
            else:
                for c in obj.classes:
                    parts.append(cls.dump_skeleton(c, files_only=files_only, depth=depth-1, pretty=pretty))

        return textwrap.indent("\n".join(parts), indent_str)
    
    @classmethod
    def dump(
        cls, 
        obj: "BaseStruct", 
        verbosity: Verbosity=Verbosity.VERBOSE, 
        indent: int = 0,
        include_body: bool = False, 
        pretty: bool = True
    ) -> str:
        if verbosity < 0: return "" # AST Tree recursion base case
        
        is_code_struct = isinstance(obj, BaseCodeStruct)
        is_directory = isinstance(obj, Directory)
        is_file = isinstance(obj, BaseFile)
        
        child_verbosity = verbosity - 1 # if not is_directory else verbosity
        
        max_lines = 5
        # if verbosity == Verbosity.FULL:
        #     max_lines = 10000
            
        indent_str = _INDENT_TAB*indent if pretty else ""
        parts = []
    
        # HEADER
        header_str = f"{obj.id}"
        if is_code_struct:
            if obj.start_line != obj.end_line:
                header_str += f" @L{obj.start_line}-{obj.end_line} | {obj.signature}"
            else:
                header_str += f" @L{obj.start_line} | {obj.signature}"
        else:
            header_str += f" | {obj.uid}"
        parts.append(header_str)
        
        if verbosity >= Verbosity.SKELETON:
            if obj.description:
                if pretty:
                    parts.append(textwrap.fill(f"{obj.description}", width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent="// ", subsequent_indent="   ", max_lines=max_lines, placeholder="..."))
                else:
                    parts.append(f"// {obj.description}")
                    
        # if verbosity >= Verbosity.SIMPLE:
        if obj.files:
            for f in obj.files:
                parts.append(cls.dump(f, verbosity=verbosity, indent=1, include_body=include_body, pretty=pretty))
        if obj.directories:
            for d in obj.directories:
                if d is obj:
                    logger.warning(f"Skipping dumping directory {d} as it is the same as its parent {obj}, likely to avoid circular reference.")
                    continue
                parts.append('\n' +cls.dump(d, verbosity=verbosity, indent=1, pretty=pretty))
        if obj.classes:
            for c in obj.classes:
                parts.append(cls.dump(c, child_verbosity, indent=1, pretty=pretty))
        # if verbosity >= Verbosity.VERBOSE:
        #     if obj.parent and obj.parent.uid:
        #         parts.insert(0, f"/{obj.parent.uid}")
        #     else:
        #         parts.insert(0, f"/{obj.path}")
        
        if verbosity >= Verbosity.VERBOSE and not is_file:
            if obj.inbound_dependency_strings:
                if pretty:
                    parts.append(textwrap.fill(f"{', '.join(obj.inbound_dependency_strings)}", width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent="<  ", subsequent_indent="   ", max_lines=max_lines, placeholder="..."))
                else:
                    parts.append(f"< {', '.join(obj.inbound_dependency_strings)}")
            if obj.outbound_dependency_strings:
                if pretty:
                    parts.append(textwrap.fill(f"{', '.join(obj.outbound_dependency_strings)}", width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent=">  ", subsequent_indent="   ", max_lines=max_lines, placeholder="..."))
                else:
                    parts.append(f"> {', '.join(obj.outbound_dependency_strings)}")
        
        if verbosity > Verbosity.SKELETON:
            if obj.fields:
                sorted_fields = sorted(obj.fields, key=lambda f: f.impact_score, reverse=True)
                n = 5
                top_fields = sorted_fields[:n]
                rest_fields = sorted_fields[n:]
                
                top_fields_strings = []
                rest_fields_strings = []
                for f in top_fields:
                    top_fields_strings.append(cls.dump(f, verbosity=max(0, child_verbosity), indent=indent+1, pretty=pretty))
                for f in rest_fields:
                    rest_fields_strings.append(cls.dump(f, verbosity=Verbosity.HEADER, indent=indent+1, pretty=pretty))
                field_str = "fields:\n" + "\n".join(top_fields_strings)
                if rest_fields_strings:
                    field_str += "\n" + "\n".join(rest_fields_strings)
                parts.append(field_str)
            
            if obj.methods:
                sorted_methods = sorted(obj.methods, key=lambda m: m.impact_score, reverse=True)
                n = 5
                top_methods = sorted_methods[:n]
                rest_methods = sorted_methods[n:]
                
                top_method_strings = []
                rest_method_strings = []
                
                for m in top_methods:
                    top_method_strings.append("\n" + cls.dump(m, verbosity=max(0, child_verbosity), indent=indent+1, pretty=pretty))
                
                for m in rest_methods:
                    rest_method_strings.append(cls.dump(m, verbosity=Verbosity.HEADER, indent=indent+1, pretty=pretty))
                    
                method_str = "methods:" + "\n".join(top_method_strings)
                if rest_method_strings:
                    method_str += "\n\n" + "\n".join(rest_method_strings)
                parts.append(method_str)
        
        if is_code_struct:
            if include_body and obj.body:
                parts.append(f"```\n{obj.body}\n```")
            
        return textwrap.indent("\n".join(parts), indent_str)
    
    # @classmethod
    # def dump_field(
    #     cls,
    #     f: BaseField,
    #     verbosity: Verbosity = Verbosity.SIMPLE,
    #     indent: int = 0,
    #     include_body: bool = False,
    #     pretty: bool = True
    # )->str:
    #     if verbosity < 0: return "" # AST Tree recursion base case
        
    #     max_lines = verbosity + 1
    #     if verbosity == Verbosity.FULL:
    #         max_lines = 10000
        
    #     indent_str = _INDENT_TAB*indent if pretty else ""
    #     parts = []
        
    #     # HEADER
    #     parts.append(f"{f.id} | {f.signature}")
        
    #     if isinstance(f, BaseFile):
    #         if verbosity >= Verbosity.FULL and f.imports:
    #             parts.append(textwrap.fill(', '.join(f.imports), width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent=_INDENT_TAB, subsequent_indent=_INDENT_TAB))
        
    #     # SKELETON
    #     if verbosity >= Verbosity.SKELETON:
    #         if f.description:
    #             if pretty:
    #                 parts.append(textwrap.fill(f"{f.description}", width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent="// ", subsequent_indent="   ", max_lines=max_lines, placeholder="..."))
    #             else:
    #                 parts.append(f"// {f.description}")

    #     # SIMPLE
    #     if verbosity >= Verbosity.SIMPLE:
    #         if f.field_type:
    #             parts.append(f"type: {f.field_type}")
        
        
    #     return textwrap.indent("\n".join(parts), indent_str)
    
    # @classmethod
    # def dump_method(
    #     cls, 
    #     m: BaseMethod, 
    #     verbosity: Verbosity = Verbosity.SIMPLE, 
    #     indent: int = 0, 
    #     include_body: bool = False,
    #     pretty: bool = True
    # ) -> str:
    #     # logger.debug(m.to_json(4))
    #     # logger.debug(f"{verbosity=}")
        
    #     if verbosity < 0: return "" # AST Tree recursion base case
        
    #     max_lines = verbosity + 1
    #     if verbosity == Verbosity.FULL:
    #         max_lines = 10000
        
    #     indent_str = _INDENT_TAB*indent if pretty else ""
    #     line_range = f"@L{m.start_line}-{m.end_line}"
    #     parts = []
        
    #     # HEADER
    #     parts.append(f"{m.id} {line_range} | {m.signature}")
        
    #     # SKELETON
    #     if verbosity >= Verbosity.SKELETON:
    #         if pretty:
    #             parts.append(textwrap.fill(f"{m.description}", width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent="// ", subsequent_indent="   ", max_lines=max_lines, placeholder="..."))
    #         else:
    #             parts.append(f"// {m.description}")

    #     # SIMPLE
    #     if verbosity >= Verbosity.SIMPLE:
    #         dependency_strings = m.outbound_dependency_strings
    #         if dependency_strings:
    #             if pretty:
    #                 parts.append(textwrap.fill(f"{', '.join(dependency_strings)}", width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent="<  ", subsequent_indent="   ", max_lines=max_lines, placeholder="..."))
    #             else:
    #                 parts.append(f"> {', '.join(dependency_strings)}")

    #     # VERBOSE
    #     if verbosity >= Verbosity.VERBOSE:
    #         if m.parent and m.parent.uid:
    #             parts.insert(0, f"{m.parent.uid}")
    #         dependency_strings = m.inbound_dependency_strings
    #         logger.debug(f"{dependency_strings=}")
    #         if dependency_strings:
    #             if pretty:
    #                 parts.append(textwrap.fill(f"{', '.join(dependency_strings)}", width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent=">  ", subsequent_indent="   "))
    #             else:
    #                 parts.append(f"< {', '.join(dependency_strings)}")
    #         # parts.append(f"# impact score: {m.impact_score}")
            
    #     # INCLUDE BODY
    #     if include_body and m.body:
    #         parts.append(f"```\n{m.body}\n```")
        
    #     return textwrap.indent(f"\n".join(parts), indent_str)
        
    # @classmethod
    # def dump_class(
    #     cls, c: BaseClass, 
    #     verbosity: Verbosity=Verbosity.SIMPLE, 
    #     indent: int = 0, 
    #     include_body: bool = False,
    #     pretty: bool = True
    #     ) -> str:
        
    #     is_enum = c.enum_constants and len(c.enum_constants)>0
        
    #     indent_str = _INDENT_TAB*indent
        
    #     parts = []
        
    #     max_lines = verbosity + 1
    #     if verbosity == Verbosity.FULL:
    #         max_lines = 10000
        
    #     line_range = f"@L{c.start_line}-{c.end_line}"
        
    #     # HEADER
    #     header_str = f"{c.id} {line_range} | {c.signature}"
    #     if is_enum:
    #         header_str += f" {{{', '.join(c.enum_constants)}}}"
    #     parts.append(header_str)
        
    #     # SKELETON
    #     if verbosity >= Verbosity.SKELETON:
    #         if pretty:
    #             parts.append(textwrap.fill(f"{c.description}", width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent="// ", subsequent_indent="   ", max_lines=max_lines, placeholder="..."))
    #         else:
    #             parts.append(f"// {c.description}")
        
    #     # SIMPLE
    #     if verbosity >= Verbosity.SIMPLE:
    #         # FIELDS
    #         if c.fields:
    #             field_strings = []
    #             for f in c.fields:
    #                 field_strings.append(cls.dump_field(f, verbosity=Verbosity.HEADER, indent=indent + 1, pretty=pretty))
    #             if len(field_strings)>0:
    #                 parts.append("fields:\n" + "\n".join(field_strings))
                
    #         # METHODS
    #         if c.methods:
    #             # logger.info(f"Found {len(c.methods)} methods")
                
    #             sorted_methods = sorted(c.methods, key=lambda m: len(m.outbound_dependencies)+len(m.inbound_dependencies), reverse=True)
    #             n = 5
    #             top_methods = sorted_methods[:n]
    #             rest_methods = sorted_methods[n:]
                
    #             top_method_strings = []
    #             rest_method_strings = []
                
    #             for m in top_methods:
    #                 top_method_strings.append("\n" + cls.dump_method(m, verbosity=max(0, verbosity-1), indent=indent + 1, pretty=pretty))
                
    #             for m in rest_methods:
    #                 rest_method_strings.append(cls.dump_method(m, verbosity=Verbosity.HEADER, indent=indent + 1, pretty=pretty))
                    
    #             method_str = "methods:\n" + "\n".join(top_method_strings)
    #             if rest_method_strings:
    #                 method_str += "\n\n" + "\n".join(rest_method_strings)
    #             parts.append(method_str)
            
    #         # for class_obj in c.child_classes.values():
    #         #     parts.append(cls.dump_class(class_obj, max(verbosity-1, Verbosity.SKELETON), indent=indent+1))
        
    #     # VERBOSE
    #     if verbosity >= Verbosity.VERBOSE:
    #         if c.parent and c.parent.uid:
    #             parts.insert(0, f"/{c.parent.uid}")
        
    #     # INCLUDE BODY
    #     if include_body and c.body:
    #         parts.append(f"```\n{c.body}\n```")
        

    #     return textwrap.indent("\n".join(parts), indent_str)
        
        
    # @classmethod
    # def dump_file(cls, f: BaseFile, verbosity: Verbosity=Verbosity.SIMPLE, indent: int = 0, include_body: bool = False, pretty: bool = True) -> str:
    #     parts = []
    #     indent_str = _INDENT_TAB*indent
        
    #     max_lines = verbosity + 1
    #     if verbosity == Verbosity.FULL:
    #         max_lines = 10000
        
    #     # HEADER
    #     parts.append(f"{f.id} | {f.uid}")
        
    #     # FULL
    #     if verbosity >= Verbosity.FULL and f.imports:
    #         parts.append(textwrap.fill(', '.join(f.imports), width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent=_INDENT_TAB, subsequent_indent=_INDENT_TAB))

    #     # SIMPLE
    #     # if verbosity >= Verbosity.SIMPLE:
    #     #     if f.fields:
    #     #         parts.append(f"fields: {', '.join(f.fields.keys())}")
    #     #     if f.methods:
    #     #         parts.append("\n".join([cls.dump_method(m, Verbosity.SKELETON, indent=indent+1, pretty=pretty) for m in f.methods.values()]))
        
    #     # SKELETON
    #     if verbosity >= Verbosity.SKELETON:
    #         for c in f.classes:
    #             parts.append(cls.dump_class(c, verbosity=verbosity-1, indent=indent+1, pretty=pretty))
                
    #     return textwrap.indent("\n".join(parts), indent_str)
    
    # @classmethod
    # def dump_parser(cls, parser: "BaseParser", verbosity: Verbosity=Verbosity.SIMPLE, pretty: bool = True) -> str:
    #     return '\n\n'.join([cls.dump_file(f, verbosity, pretty=pretty) for f in parser.files])
    
    # @classmethod
    # def dump_files(cls, files: list[BaseFile], verbosity: Verbosity=Verbosity.SIMPLE, pretty: bool = True)->str:
    #     return '\n' + '\n\n'.join([cls.dump_file(f, verbosity, pretty=pretty) for f in files])
