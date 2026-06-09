# Creating a New Language Parser in Tostr

This guide outlines the process for adding support for a new programming language to Tostr.

## 1. Prerequisites & Environment Setup

Before starting the implementation, ensure the Tree-sitter grammar for the language is installed and registered.

### Install Tree-sitter Grammar
1. Find the official tree-sitter package for the language (e.g., `tree-sitter-python`).
2. Add it to `pyproject.toml` and `requirements.txt`.
3. Install it:
   ```bash
   pip install tree-sitter-<language>
   ```

### Discovering Tree-sitter Syntax
To write effective builders and queries, you need to know the exact node types used by the Tree-sitter grammar. Use this Python snippet to inspect the AST of a sample file:

```python
from tree_sitter import Parser
from tree_sitter_python import language # Replace with your language

parser = Parser(language())
with open("path/to/sample_file.py", "rb") as f:
    tree = parser.parse(f.read())

def print_tree(node, depth=0):
    print("  " * depth + f"{node.type} [{node.start_point} - {node.end_point}] field={node.field_name_for_child(0)}")
    for child in node.children:
        print_tree(child, depth + 1)

print_tree(tree.root_node)
```

## 2. File Structure

Create a new directory in `src/tostr/languages/`:
```
src/tostr/languages/<lang>/
├── __init__.py
├── language.py      # Exports the TREE_SITTER_LANGUAGE object
├── queries.py       # Tree-sitter SCM queries (e.g., for method calls)
├── builders.py      # Language-specific Builder implementations
└── default.tostrignore # Default ignore patterns for this language
```

## 3. Implementing Builders

You must extend the base builders from `tostr.core.builders`.

### `BaseBuilder`
Acts as a factory for specific builders (`File`, `Class`, `Method`, `Field`).

### `BaseFileBuilder`
- Responsible for parsing a file and identifying its children (classes, functions, etc.).
- Must handle imports and package/module names.
- **Python/Go Consideration:** Files often contain free-floating functions. Ensure these are added as children directly to the `BaseFile` object.

### `BaseClassBuilder`
- Parses class definitions.
- Extracts inheritance information (`inherits` list).
- Parses class body for children (methods, fields, inner classes).

### `BaseMethodBuilder`
- Parses function/method definitions.
- Extracts `arity`.
- **Crucial:** Uses `Query` and `QueryCursor` with language-specific SCM queries from `queries.py` to identify `dependency_names`.
- `dependency_names` should be a list of tuples: `(name, arity, receiver, is_creation)`.

## 4. Tree-sitter Queries (`queries.py`)

Define SCM queries to find method calls and object creations. 
Example (Java):
```python
DEPENDENCY_QUERY = """
(method_invocation
  receiver: (identifier) @receiver
  name: (identifier) @name
  arguments: (argument_list) @args) @method_call

(object_creation_expression
  type: (type_identifier) @type
  arguments: (argument_list) @args) @object_creation
"""
```

## 5. Registration

Register the new language builders in `src/tostr/core/providers.py` so the `StructBuilderProvider` can serve them based on file extensions.

## 6. Verification Checklist
- [ ] Tree-sitter dependency added to `pyproject.toml` and `requirements.txt`.
- [ ] `language.py` correctly exports the language object.
- [ ] `builders.py` implements all necessary `from_node` methods.
- [ ] `queries.py` covers method calls and object creation.
- [ ] Extension registered in `providers.py`.
- [ ] Unit tests created in `tests/languages/<lang>/`.
