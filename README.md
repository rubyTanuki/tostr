<p align="center">
    <a href="https://toastedtools.com/"><img src="./resources/logo.png" alt="Tostr Logo" width="816"></a>
</p>

<h1 align="center">
Frontloading Agentic AI Code Context
</h1>

<p align="center">
    <img src="./resources/demo.gif" alt="Demo GIF" width="860">
</p>

<p align="center">
Tostr is a CLI and MCP agent context engine which greatly reduces token costs and context bloat for agentic LLM coding assistants by pre-computing an llm-described AST with outputs in the highly-efficient .tost format
</p>

# Features
### 🌴 Pre-computed Abstract Syntax Tree
Tostr scrapes your project on initialization, building a comprehensive Abstract Syntax Tree IR (Intermediate Representation) of the entire OOP code structure and stores it in a local SQLite database.

### ⛓️ Heuristic Dependency Graph Resolution
Tostr resolves dependencies between structures in your code, building a dependency graph to allow agents to traverse inbound or outbound method calls efficiently.

### 🔌 MCP and CLI interfaces
Tostr has both a CLI and MCP interface, allowing llms to boot up the mcp server for larger development sessions, while allowing agents or human developers to utilize the CLI for individual actions or quick, manual AST traversals.

### ⛓️‍💥 Automatic Incremental Change Diffs
While the MCP server is running, Tostr identifies the subtree of the AST which was updated on file save, add, or delete, then re-scrapes and re-describes exactly the section that was updated, ensuring that the AST is instantly up-to-date during development.

### 🗄️ Lightweight SQLite Cache
The AST IR and Dependency Graph is cached to an on-drive SQLite .db file to vastly increase efficiency of agent AST traversals, as well as allow the AST to be directly queried via sql commands.

### 💭 Semantic Vector Embedding 
Using local ONNX (Open Neural Network Exchange) weights from the all-MiniLM-L6-v2 embedding model, tostr embeds the descriptions of each struct, allowing for far more accurate semantic search of specific structs than the traditional line blocking approach.

# Quick Start

## Installation
Tostr is available on PyPI and can be installed via `pip` or `pipx`. Due to its dependencies, it is **highly recommended** to install it using `pipx` to keep it in an isolated environment:

```bash
% pipx install tostr
```

Alternatively, you can install it via standard `pip`:
```bash
% pip install tostr
```

## Initializing Tostr
Before being able to use Tostr, the repository must be initialized using the CLI or MCP.

To manually initialize the repository, cd to the root of the project and run:
```
% tostr init . --ignore 'default'
```
This creates the `.tostr` directory and initializes the default `.tostrignore` to exclude environment files, node_modules, build artifacts, and other files which are not needed in the project AST.

## Using the CLI
Once the project is initialized, Tostr is ready to go! The CLI provides a rich, interactive way to explore your project's structure.

### Project Skeleton
To see the high-level structure of your project, run:
```
% tostr skeleton . --depth 1
```
Tostr will print a beautiful tree structure of your root and its direct children.

<img src="./resources/skeleton_example.png" alt="Skeleton Example" width="560">


> The `depth` parameter determines how many layers into the file tree should be skeletonized (default is 7).

### Searching Structs
You can search for specific code components using semantic natural language queries:
```
% tostr search "PID controller"
```
<img src="./resources/search_example.png" alt="Search Example" width="860">

### Inspecting Structs
Each struct (file, class, method, or field) can be inspected for deep detail, including its LLM-generated description and dependency graph:

```
% tostr inspect C-c7766e98fa .
```

<img src="./resources/inspect_example_1.png" alt="Inspect Example 1" width="860">

#### Inspect Flags:
* `--body`: Attaches the syntax-highlighted source code of the struct being inspected.
* `--raw`: Disables rich formatting and indentation for raw output.
* `--max-lines`: Limits the output length (useful for large classes).

```
% tostr inspect M-bc1cb7aeff --body .
```
<img src="./resources/inspect_example_2.png" alt="Inspect Example 2" width="760">


#### Contributing

See [CONTRIBUTING.md](https://github.com/rubyTanuki/tostr/blob/main/CONTRIBUTING.md) for instructions on how to contribute to the Tostr source code
