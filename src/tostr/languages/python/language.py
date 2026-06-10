from __future__ import annotations
import tree_sitter_python as tspython
from tree_sitter import Language

PYTHON_LANGUAGE = Language(tspython.language())
