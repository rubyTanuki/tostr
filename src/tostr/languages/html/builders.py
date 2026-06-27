from __future__ import annotations
from tree_sitter import Parser
from pathlib import Path
import hashlib

from tostr.core.builders import BaseBuilder, BaseFileBuilder, line_bounds
from tostr.languages.html.language import HTML_LANGUAGE
from tostr.core.models import BaseFile, BaseStruct


class HtmlBuilder(BaseBuilder):
    """HTML is parsed at the file level only: an HTML document has no functions or
    classes to map onto the struct model, so we emit a single BaseFile (described and
    embedded for semantic search) and extract no children. Dependency resolution is the
    no-op BaseDependencyResolver (see LanguageProvider.get_resolver)."""

    def build_file(self) -> HtmlFileBuilder:
        return HtmlFileBuilder(self.registry)


class HtmlFileBuilder(BaseFileBuilder):
    def from_path(self, path: Path, parent: BaseStruct = None) -> BaseFile:
        file_obj = super().from_path(path, parent=parent)

        with open(path, "rb") as f:
            body_bytes = f.read()
        file_obj.body = body_bytes.decode("utf-8", errors="replace")
        file_obj.diff_hash = hashlib.md5(body_bytes).hexdigest()

        # Parse the document so the file is skeletonizable (BaseStruct.skeletonize needs
        # a tree-sitter node). No children are extracted from the tree.
        parser = Parser(HTML_LANGUAGE)
        tree = parser.parse(body_bytes)
        file_obj.node = tree.root_node
        file_obj.start_line, file_obj.end_line = line_bounds(tree.root_node)

        return file_obj
