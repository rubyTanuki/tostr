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
- **Import Normalization:** To keep dependency resolution agnostic, normalize all imports into a standard `namespace.Member` or `namespace.*` format in the `imports` list.
- **Relative Imports:** Handle relative imports (e.g., `from . import x`) by resolving them against the current file's package path.
- **Python/Go Consideration:** Files often contain free-floating functions. Ensure these are added as children directly to the `BaseFile` object.
- **Decorators:** Some grammars (like Python) wrap decorated classes/functions in a `decorated_definition` node. Your builder must handle these by extracting the inner definition node.

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

## 5. Dependency Resolution (`resolver.py`)

Tostr uses a Strategy pattern for dependency resolution.

- **`BaseDependencyResolver`**: Handles generic resolution (local lookups, basic normalized import matching, receiver heuristics).
- **Custom Resolvers**: If your language has unique resolution rules (e.g., specific wildcard behaviors or complex scoping), create a `<Lang>DependencyResolver` in `src/tostr/core/resolver.py` and register it in `Registry.get_resolver()`.
- **Arity Matching:** By default, Tostr uses strict arity matching (argument count). For dynamic languages like Python (with default/keyword args), set `self.strict_arity = False` in your custom resolver's `__init__`.
- **Receiver Heuristics:** The resolver attempts to find the type of a receiver (e.g., `obj` in `obj.method()`) by checking local fields. For module-based calls, it should also check the file's normalized imports.

## 6. Registration

1. Register the new language builders in `src/tostr/core/providers.py` so the `StructBuilderProvider` can serve them based on file extensions.
2. Update `Registry.get_resolver()` in `src/tostr/core/registry.py` if a custom resolver was implemented.

## 7. Verification Checklist
- [ ] Tree-sitter dependency added to `pyproject.toml` and `requirements.txt`.
- [ ] `language.py` correctly exports the language object.
- [ ] `builders.py` implements all necessary `from_node` methods.
- [ ] `queries.py` covers method calls and object creation.
- [ ] Extension registered in `providers.py`.
- [ ] Unit tests created in `tests/languages/<lang>/`.

## 8. Advanced Lessons & Troubleshooting

### Handling Tree-Sitter Node Wrapping
In many languages, a definition (Class/Function) can be wrapped by decorators. In Python, a decorated class isn't a `class_definition` at the top level of the `module`; it's a `decorated_definition` containing a `class_definition`. Your `FileBuilder` and `ClassBuilder` must account for this nesting to avoid "disjointed" or missing structs.

### The "Arity Trap" in Dynamic Languages
Java requires exact arity matching because of method overloading. Python does not. If your language supports default arguments, strict arity matching will cause almost all dependency resolutions to fail. Ensure your language's `Registry.resolve_methods` calls pass `arity=None` or use a resolver with `strict_arity=False`.

### Performance: The Bubble-up Storm
Tostr's graph model bubbles dependencies up from Methods to Classes to Files to Directories. In large projects with wildcard imports (`from x import *`), a failed strict match can trigger thousands of "fuzzy" dependency links. To prevent hangs:
1. Ensure your `BaseStruct.add_dependency` and `add_fuzzy_dependency` implementations return early if the target is already in the set.
2. Favor resolving receivers to specific imports before falling back to wide-scope wildcard matching.

### Unified Calls and Instantiations
If your language uses the same syntax for calling a function and instantiating a class (like Python `MyClass()`), the resolver should attempt to resolve the name as a Type/Class if it fails to find a matching Method.
