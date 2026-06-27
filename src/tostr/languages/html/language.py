from __future__ import annotations
import tree_sitter_html as tshtml
from tree_sitter import Language

HTML_LANGUAGE = Language(tshtml.language())
