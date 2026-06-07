from __future__ import annotations
from tostr.core.models import *

from enum import IntEnum
from loguru import logger

import textwrap

_INDENT_TAB = "    "

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

        one_child = len(obj.all_children) == 1
        
        child_verbosity = verbosity - 1 # if not is_directory else verbosity
        if one_child:
            child_verbosity = verbosity
        
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
            if obj.description and not one_child:
                if pretty:
                    parts.append(textwrap.fill(f"{obj.description}", width=_LINE_WRAP_WIDTH-len(indent_str), initial_indent="// ", subsequent_indent="   ", max_lines=max_lines, placeholder="..."))
                else:
                    parts.append(f"// {obj.description}")
                    
        # if verbosity >= Verbosity.SIMPLE:
        if obj.files:
            for f in obj.files:
                parts.append(cls.dump(f, verbosity=verbosity, indent=1, include_body=include_body and one_child, pretty=pretty))
        if obj.directories:
            for d in obj.directories:
                parts.append('\n' +cls.dump(d, verbosity=verbosity, indent=1, pretty=pretty, include_body=include_body and one_child))
        if obj.classes:
            for c in obj.classes:
                parts.append(cls.dump(c, child_verbosity, indent=1, pretty=pretty, include_body=include_body and one_child))
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