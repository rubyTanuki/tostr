<p align="center">
    <a href="https://tostr.ai/"><img src="./resources/logo.png" alt="Tostr Logo" width="816"></a>
</p>

<h1 align="center">
Frontloading Agentic AI Code Context
</h1>

<p align="center">
    <img src="./resources/demo.gif" alt="Demo GIF" width="860">
</p>

<p align="center">
Tostr is a CLI and MCP agent context engine which greatly reduces token costs and context bloat for agentic LLM coding assistants by pre-computing an llm-described AST with outputs in the highly-efficient .tost format.
</p>

# Features
### 🌴 Pre-computed Abstract Syntax Tree
Tostr scrapes your project when you parse it, building a comprehensive Abstract Syntax Tree IR (Intermediate Representation) of the entire OOP code structure and stores it in a local SQLite database.

### ⛓️ Heuristic Dependency Graph Resolution
Tostr resolves dependencies between structures in your code, building a dependency graph to allow agents to traverse inbound or outbound method calls efficiently.

### 🔌 MCP and CLI interfaces
Tostr has both a CLI and MCP interface, allowing llms to boot up the mcp server for larger development sessions, while allowing agents or human developers to utilize the CLI for individual actions or quick, manual AST traversals.

### ⛓️‍💥 Automatic Incremental Change Diffs
While the MCP server is running, Tostr identifies the subtree of the AST which was updated on file save, add, or delete, then re-scrapes and re-describes exactly the section that was updated, ensuring that the AST is instantly up-to-date during development.

### 🗄️ Lightweight SQLite Cache
The AST IR and Dependency Graph is cached to an on-drive SQLite .db file to vastly increase efficiency of agent AST traversals, as well as allow the AST to be directly queried via sql commands.

### 💭 Semantic Vector Embedding 
Using local ONNX (Open Neural Network Exchange) weights from the all-MiniLM-L6-v2 embedding model, Tostr embeds the descriptions of each struct, allowing for far more accurate semantic search of specific structs than the traditional line blocking approach.

## 🌍 Language Support Matrix

Tostr is designed to map the macro-architecture of your codebase. Most supported languages receive high-density **Structural AST Skeletons** and **AI Semantic Descriptions**, while multi-hop cross-file dependency resolution is currently optimized specifically for deep backend monoliths (Java). Some formats (e.g. HTML) have no extractable sub-structures and are indexed at the **file level** — a single described, searchable node per file rather than a skeleton of classes and functions.

| Language | Extensions | Structural AST Parsing | AI Semantic Descriptions | Cross-File Dependency Graph |
| :--- | :--- | :---: | :---: | :---: |
| **☕ Java** | `.java` | ✅ | ✅ | ✅ |
| **🐍 Python** | `.py` | ✅ | ✅ | ✅ |
| **🌐 HTML** | `.html`, `.htm` | 📄 File-level | ✅ | — |
| **🔷 TypeScript / JavaScript** | `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs` | 🚧 Coming Soon | 🚧 Coming Soon | 🚧 Coming Soon |
| **🎯 C#** | `.cs` | 🚧 Coming Soon | 🚧 Coming Soon | 🚧 Coming Soon |
| **🐹 Go** | `.go` | 🚧 Coming Soon | 🚧 Coming Soon | 🚧 Coming Soon |

*Tostr is still in active development, so this list will quickly expand and grow with more language support. If you want to add support for your favorite language, you can also take a look at [CONTRIBUTING.md](https://github.com/rubyTanuki/tostr/blob/main/CONTRIBUTING.md) to help us out!*

> **Note for AI Agents:** For languages where dependency tracking is marked "Coming Soon" (or "—" for file-level formats), the MCP server will cleanly omit the dependency fields. Agents should rely on `tostr skeleton` and semantic `search` to navigate these codebases.

# 60 Second Quickstart
Zero config required. Paste these into a terminal — shown for Claude Code; [other agents below](#connecting-the-mcp-to-your-agent).
```
pipx install tostr                          # Installing the CLI onto your PATH

tostr add-agent claude --global             # Tells the agent to prefer Tostr for navigation
claude mcp add tostr -- tostr start-mcp     # connect the MCP server

cd path/to/project                          # Navigate to your project repository root

tostr parse . --no-llm                      # build the local AST cache (no API key needed)

tostr status .                              # confirm the parse succeeded

# now explore from the CLI — or just ask your agent:
tostr skeleton . --files-only
tostr search "authentication" --filter class
```
For richer descriptions and sharper semantic search, add a `GEMINI_API_KEY` and drop `--no-llm` — see [Getting Started](#getting-started).

# Getting Started

## Prerequisites
* Requires Python 3.12+
* Requires a Google Gemini API Key for descriptions

## Installation
Tostr is available on PyPI and can be installed via `pip` or `pipx`. Due to its dependencies, it is **highly recommended** to install it using `pipx` to keep it in an isolated environment:

```bash
pipx install tostr
```
> If you don't have pipx, you can download it easily via `brew install pipx` on mac or `python -m pip install --user pipx; python -m pipx ensurepath` on windows.

Alternatively, you can install it via standard `pip`:
```bash
pip install tostr
```
or with `uv` for faster installation:
```bash
uv tool install tostr
```

If you wish to utilize tostr's struct descriptions, you will also need to configure a Google Gemini API key and save it as an environment variable. This is optional, as the embedding will just fall back to using code bodies and UIDs when a description isnt generated.

To create a new API key:
1. Go to the [Google AI Studio](https://aistudio.google.com/) and log in with your google email.
2. Once logged in, in the bottom left click the `Get API Key` button.
3. In the top right, click `Create API Key`. You may need to create a new project before making an API key. You can just name it `tostr`
4. Name the key something like `Tostr API Key`. This name does not matter for the rest of the steps.
5. Click the button next to the new key that says `copy API key` to copy the string to your clipboard. It should be a long random string with 39 characters.
6. Save this key as an environment variable called `GEMINI_API_KEY` on your computer.

**DISCLAIMER**: While tostr does not use any gemini features that require a payment method, you will very quickly hit rate limits on a free tier. 

I would suggest setting up a payment method in the Google AI Studio so you can get the limits of the Tier 1 payment tier. Once set up, using tostr should cost only a couple cents per project if anything, since it uses the `Gemini Flash-Lite` model for all its description generation. You can very easily set a spend limit in Google's UI if you like by going to the `Spend` tab after creating your key.

#### Installing Environment Variables on Mac:
To expose your API key to tostr in a specific terminal session, run this command:
```bash
export GEMINI_API_KEY=[your api key]
```
> This will only save the key in the current session. To save the key permanently and system-wide, follow the instructions [here](https://www.youtube.com/watch?v=nfcAcfpeQ0Q)

#### Installing Environment Variables on Windows:
In order to save environment variables on Windows, follow these steps.

1. Press the windows key and type `environment variables`
2. Click `Edit the system environment variables` to open the System Properties window.
3. Decide where to store your variable.
    * **User variables**: Only accessible by your specific Windows account.
    * **System variables**: Accessible by all users on the computer (requires Administrator privileges).
4. Click `New...` under the chosen section
5. Enter `GEMINI_API_KEY` in the name, and paste your API key from the Google AI Studio
6. Click OK on all open windows to save the settings.
> Note: You must restart any open command prompts for them to recognize the new variable.

## Connecting the MCP to your agent

Tostr can be used as an MCP (Model Context Protocol) server, allowing your favorite AI coding agent to interact directly with your project's AST and dependency graph.

### Generic Configuration
Most MCP-compatible agents use a JSON configuration file. You can generally add Tostr by adding the following to your `mcpServers` configuration:

```json
{
  "mcpServers": {
    "tostr": {
      "command": "tostr",
      "args": ["start-mcp"],
      "env": {
        "GEMINI_API_KEY": "YOUR_API_KEY_HERE"
      }
    }
  }
}
```

> **Note**: If `tostr` is not in your system PATH, you may need to provide the absolute path to the executable (e.g., `/Users/YOUR_NAME/.local/bin/tostr`). You can find this path by running `which tostr` on macOS/Linux or `where tostr` on Windows.

### Claude Code: one-line install

If you're on Claude Code, skip the JSON entirely — paste this into your terminal and you're connected:

```
claude mcp add tostr --env GEMINI_API_KEY=YOUR_API_KEY_HERE -- tostr start-mcp
```
or even simpler, if you configure your projects to use no-llm:
```
claude mcp add tostr -- tostr start-mcp
```

Claude Code's CLI writes the config for you, no file editing required.

### Popular Agents with MCP Support
Below are instructions and links for setting up MCP servers in common AI coding environments:

*   **Claude Desktop**: [Official Setup Guide](https://modelcontextprotocol.io/quickstart/user)
*   **Cursor**: [Cursor MCP Documentation](https://docs.cursor.com/mcp)
*   **Cline (VS Code)**: [Cline Documentation](https://docs.cline.bot/mcp/mcp-overview)
*   **Codex**: [Codex Documentation](https://developers.openai.com/codex/mcp)

### tostr add-agent — teach your agent to prefer Tostr

Connecting the MCP server gives your agent the Tostr *tools*; it doesn't tell it *when* to reach for them over raw `read`/`grep`. `add-agent` installs that guidance into your agent's instructions file (`CLAUDE.md`, `.clinerules`, etc.) so the agent defaults to `skeleton`/`search`/`inspect` for code navigation.

```
tostr add-agent claude        # install into ./CLAUDE.md
tostr add-agent cursor        # install into ./.cursor/rules/tostr.mdc
tostr add-agent all           # install into every supported agent
tostr add-agent claude -g     # install into your global ~/.claude/CLAUDE.md instead
tostr add-agent --list        # show supported agents and their config paths
```

Supported agents: `claude`, `cline`, `copilot`, `codex`, `cursor`.

It is **safe to re-run and non-destructive**: the guidance is written between managed markers, so installing into a file that already has your own content just upserts that block and leaves everything else untouched (re-running an unchanged install is a no-op). Agents whose config is a dedicated file (Cursor's `tostr.mdc`) are written whole.

To uninstall, use `tostr remove-agent` — it strips the managed block (deleting the file only if it becomes empty) or removes the dedicated file:

```
tostr remove-agent claude
tostr remove-agent all
```

**Available Flags** (`add-agent`):
- `--global`, `-g`: Install into the agent's global config instead of the current project. Only some agents have a global location (e.g. `claude`, `codex`). Default is `False`
- `--force`, `-f`: Overwrite a dedicated agent file (e.g. Cursor's `tostr.mdc`) even if it isn't Tostr-managed. Default is `False`
- `--list`, `-l`: List supported agents and where they install, then exit.
- `--debug`, `--no-debug` / `-d`, `-nd`: Enable debug logging. Default is `False`

## Setting up Tostr

Tostr separates **authoring configuration** from **building the cache**:

- **`tostr.toml`** (project root, committed) holds your project settings, and **`.tostrignore`** (project root, committed) holds your ignore rules. These are *yours* — you edit them and they survive any cache wipe.
- **`.tostr/`** (hidden, gitignored) is generated and disposable. `tostr parse` rebuilds it from scratch; `tostr clean` removes it.
- **`tostr.lock.json`** (project root, *generated-but-committed*) is an optional third category — the AST equivalent of a `package-lock.json`. You produce it with `tostr export`, commit it, and it lets a teammate's first `tostr parse` reuse your LLM-generated descriptions instead of paying to regenerate them. See [`tostr export`](#tostr-export) below.

### tostr init — scaffold project files (optional)

```
tostr init .
```
This lays down the editable project files so you have something concrete to configure:
- creates `tostr.toml` at the root, pre-filled with documented defaults;
- creates `.tostrignore` at the root, materialized from the default templates (environment files, build artifacts, `node_modules/`, `venv/`, `target/`, etc.) for your language(s);
- creates the empty `.tostr/` directory and adds it to your `.gitignore`.

`init` **does not parse** and never needs an API key. It is also **idempotent**: it never overwrites an existing `tostr.toml` or `.tostrignore` (pass `--force` to overwrite). `init` is entirely optional — if you're happy with the defaults you can skip straight to `tostr parse`, which falls back to the same built-in defaults without writing any files.

**Available Flags**:
- `--force`, `-f`: Overwrite existing authored files (`tostr.toml`, `.tostrignore`) instead of leaving them untouched. Default is `False`
- `--debug`, `--no-debug` / `-d`, `-nd`: Enable debug logging. Default is `False`

### tostr parse — build the database

```
tostr parse .
```
This does the actual work: it parses the AST, resolves dependencies, generates descriptions, embeds them, and writes `.tostr/cache.db`. It **reads** your configuration (or the built-in defaults) and authors nothing. Run it whenever you want to (re)build the cache.

The `--language` flag overrides the configured language for this run only. If omitted, `parse` uses the `language` from `tostr.toml` (defaulting to `auto`, which parses every file with a supported extension and treats them all as valid dependency nodes). Choosing a specific language parses only that extension.

> Tostr currently supports `.java`, `.py`, and `.html`/`.htm`, so the options for `--language` are `java`, `python`, and `html`.

If you are running tostr on a project that already has an existing database but you want to reparse from the start, use the `--no-cache` flag.

If a committed `tostr.lock.json` is present (see [`tostr export`](#tostr-export)), `parse` automatically **seeds** descriptions from it: for any struct whose code is unchanged since the lockfile was written (matched on a content hash), it reuses the committed description instead of calling the LLM, then re-embeds locally for free. This is what lets a teammate run `git clone && tostr parse` and get the shared descriptions without an API key for the unchanged majority of the code — only genuinely new or changed code hits the LLM.

The `--llm` flag selects which LLM strategy generates descriptions for this run only. Resolution is `--llm` > the strategy configured in `tostr.toml` > the `gemini` default. Gemini is the only built-in default and reads `GEMINI_API_KEY` from the environment; if that key is missing and no other strategy is configured, `parse` stops and tells you to configure a binding or set the key (use `--no-llm` to skip descriptions entirely). Pass `--llm ollama` to describe against a local [Ollama](https://ollama.com) model instead, or `--llm none` to disable description generation (equivalent to `--no-llm`).

> Configuring a strategy's details (model name, host, etc.) is done per-strategy in `tostr.toml`; see the strategy configuration docs for the available keys.

**Available Flags**:
- `--use-cache`, `--no-cache`: Load the existing cache if it exists (use `--no-cache` to force a full reparse from scratch). Default is `True`
- `--language`, `-l`: Override the configured language for this run (e.g., `java`, `python`). Omit to use `tostr.toml` (defaults to `auto`).
- `--llm`: Override the LLM strategy for this run (`gemini`, `ollama`, or `none` to disable). Trumps `tostr.toml`. Omit to use the configured strategy (default `gemini`).
- `--no-llm`: Skip LLM-generated descriptions (no API key required); equivalent to `--llm none`. Embeddings still run, falling back to code context. Default is `False`
- `--debug`, `--no-debug` / `-d`, `-nd`: Enable debug logging. Default is `False`

## Traversing the graph
Once the project is parsed, Tostr is ready to go! The CLI provides a rich, interactive way to explore your project's structure.

### Project Skeleton
To see the high-level structure of your project, run:
```
tostr skeleton . --depth 1
```
Tostr will print a beautiful tree structure of your root and its direct children.

<img src="./resources/skeleton_example.png" alt="Skeleton Example" width="560">

**Available Flags**:
- `--pretty`, `--raw`: Pretty format output with line wrapping and indentation (disable for raw output). Default is `True`
- `--depth`, `-d`: Depth to traverse for skeleton generation. Default is `4`
- `--files-only`, `-f`: Only generate the skeleton for files, skipping individual classes/methods. Default is `False`
- `--max-lines`, `-m`: Maximum number of lines to include in the output. Default is `500`
- `--debug`, `--no-debug`: Enable debug logging. Default is `False`

### Searching Structs
You can search for specific code components using semantic natural language queries:
```
tostr search "PID controller"
```
<img src="./resources/search_example.png" alt="Search Example" width="860">

> Tostr uses the llm described descriptions instead of source code for its vector embeddings, avoiding one of the major downfalls of codebase semantic search; raw code does not encapsulate surrounding context or intent, but the descriptions do, making for a far more consistent semantic search.
**Available Flags**:
- `--filter`, `-f`: Filter results by struct type (e.g., `class`, `method`). Default is none (no filter)
- `--top-k`, `-k`: Number of results to return. Default is `5`
- `--debug`, `--no-debug`: Enable debug logging. Default is `False`

### Inspecting Structs
Each struct (file, class, method, or field) can be inspected for deep detail, including its LLM-generated description and dependency graph:

```
tostr inspect C-c7766e98fa .
```

<img src="./resources/inspect_example_1.png" alt="Inspect Example 1" width="860">

```
tostr inspect M-bc1cb7aeff --body .
```
<img src="./resources/inspect_example_2.png" alt="Inspect Example 2" width="760">

**Available Flags**:
- `--body`, `--no-body`: Attach the syntax-highlighted source code of the struct being inspected. Default is `False`
- `--pretty`, `--raw`: Pretty format output with line wrapping and indentation (disable for raw output). Default is `True`
- `--max-lines`, `-m`: Maximum number of lines to include in the output (useful for large classes). Default is `500`
- `--debug`, `--no-debug`: Enable debug logging. Default is `False`


## Other Commands

Beyond traversing the graph, Tostr provides a handful of commands for managing the database, keeping it in sync, and running the MCP server. Every command accepts an optional `path` argument (defaulting to the current directory `.`) pointing at the project root, and every command supports `--debug` / `--no-debug` (`-d` / `-nd`) to enable debug logging.

### tostr status
Show whether Tostr has built a cache for a project, along with the database location, size, last-updated time, and per-type struct counts.
```
tostr status .
```
**Available Flags**:
- `--debug`, `--no-debug` / `-d`, `-nd`: Enable debug logging. Default is `False`

### tostr watch
Watch the project for file changes and incrementally update the SQLite database as you save, add, or delete files. This runs in the foreground until interrupted (the MCP server performs the same incremental diffing automatically while running).
```
tostr watch .
```
**Available Flags**:
- `--debug`, `--no-debug` / `-d`, `-nd`: Enable debug logging. Default is `False`

### tostr clean
Remove the generated `.tostr/` cache (the AST and dependency graph), so `tostr parse` can rebuild from scratch or to reclaim space. Your authored config (`tostr.toml`, `.tostrignore`) is **preserved** — `clean && parse` returns to a fresh build with your settings intact. Pass `--purge` to also delete the authored config for a full reset.
```
tostr clean .
```
**Available Flags**:
- `--purge`: Also delete authored config (`tostr.toml`, `.tostrignore`), not just the generated `.tostr/` cache. Default is `False`
- `--debug`, `--no-debug` / `-d`, `-nd`: Enable debug logging. Default is `False`

### tostr export
Snapshot the project's LLM-generated descriptions into a committed `tostr.lock.json` so teammates can reuse them instead of re-calling the LLM. Run it after a `tostr parse` produces descriptions, then commit the lockfile alongside your code:
```
tostr export .
```
On a teammate's machine, `git clone && tostr parse` then seeds those descriptions for free — every struct whose code hasn't changed (matched on a content hash) reuses your description and only re-embeds locally; no API key is needed for the unchanged majority. If the code has diverged, the affected structs simply regenerate, so a stale lockfile is self-healing.

The lockfile is **only** written by this command — `parse` reads it but never rewrites it, so running `parse` (or the live watcher) never dirties your git tree. Re-run `tostr export` whenever you want to refresh the committed descriptions. By default only descriptions are exported (vectors recompute for free from the local model); pass `--with-vectors` for literal zero recompute at the cost of a larger, merge-noisier file.

**Available Flags**:
- `--with-vectors`: Also export embedding vectors, not just descriptions. Off by default. Default is `False`
- `--debug`, `--no-debug` / `-d`, `-nd`: Enable debug logging. Default is `False`

### tostr start-mcp
Start the bare MCP server, which then awaits agent initialization over the Model Context Protocol. This is the command referenced in the [MCP configuration](#connecting-the-mcp-to-your-agent) above; you generally won't run it manually, as your agent launches it for you.
```
tostr start-mcp
```
This command takes no flags.

### Contributing to Tostr

See [CONTRIBUTING.md](https://github.com/rubyTanuki/tostr/blob/main/CONTRIBUTING.md) for instructions on how to contribute to the Tostr source code
