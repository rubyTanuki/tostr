# Architecture

## Overview
Tostr is a CLI/MCP tool for agentic programming which pre-computes context in a code repository, allowing LLMs to reason over the code required to solve a problem without seeing a single line. It constructs a repo-wide AST (abstract syntax tree) + dependency graph, stored locally in a sqlite database with struct-level, context-aware descriptions and vector embeddings for efficient traversal. By exposing this graph to an LLM via MCP, token input costs during agentic programming can be reduced by upwards of 70%. Unique to tostr in the code graph landscape is live, efficient subgraph reparsing using a file watcher attached to the mcp server's lifetime, allowing the graph to evolve and progress dynamically as the developer and agent make changes. The graph will **always** represent the project as accurately as an initial parse within seconds of agentic or human changes.

<!-- ## 2. High-Level Pipeline -->
<!-- parse → resolve dependencies → carry over cache → seed lockfile → des
cribe → embed → save.
     A diagram would go here. -->

## High Level Module Heirarchy

### Primary Dataflow Layers
* **Entrypoints** (`cli.py` / `server.py`): Expose the user interaction surface via FastMCP and a Typer CLI
* **Orchestration** (`commands.py`, `core/parser.py`): Orchestrate the dataflow for the entrypoints and handle dependency injection
* **AST Parsing** (`core/builders.py`, `languages/*`): Constructing the AST in-memory using tree-sitter
* **Dependency Resolution** (`core/resolver.py`): Deterministically building a project-wide dependency graph
* **Describing** (`core/describer.py`): Handles the description process, traversing the AST using a visitor pattern in a post-order DFS
* **Embedding** (`semantic/embeddings/*`): Handles the asyncronous enqueuing and execution of the description-based vector embeddings

### Helper Modules
* **Memory Registry** (`core/registry.py`): The in-memory representation of the project AST, acting as the struct-level interface with the database cache
* **Struct Models** (`core/models.py`): Hierarchal OOP @dataclass implementations for representing language-agnostic AST nodes (Directory, File, Class, Method, Field)
* **LLM Strategy Pattern** (`semantic/llm/*`): A generic LLMClient handling retries and async llm calls, with a polymorphised strategy pattern for different llm API bindings
* **Embedder Strategy Pattern** (`semantic/embeddings/*`): A generic EmbeddingClient handling async queue management, with a polymorphised strategy pattern for different embedding model bindings
<!-- progress tracker, db client, exceptions, serializer, lockfile, logger, config, providers, tests -->