# Design: Separating `init` and `parse`

Status: proposed
Last updated: 2026-06-19

## 1. Motivation

Today a single `tostr init` command does three unrelated things in one breath
(`commands.py::init_async`):

1. **Authors config** — writes `.tostr/config.toml` (language) and lays down
   `.tostrignore` templates.
2. **Owns generated state** — creates `.tostr/`, wipes incompatible caches.
3. **Does the work** — parses, resolves, describes, embeds, writes `cache.db`.

Mixing "create the configuration" with "use the configuration" in one step is
awkward: the user has no opportunity to review or edit config before it is
consumed, and re-running `init` to re-parse silently rewrites their settings.

There are also two latent bugs in the current flow:

- **Non-idempotent in inconsistent ways:** `config.toml` is written mode `'w'`
  (overwrites) while `.tostrignore` is mode `'a'` (appends). Re-running `init`
  *duplicates* ignore content but *resets* config.
- **`clean` deletes authored files:** `clean_db` removes `.tostr/` *and* unlinks
  `.tostrignore`, destroying user-authored configuration along with the cache.

## 2. Guiding principle: authored vs generated

The organizing rule for the whole design:

> **Root = authored.** The user writes it, commits it, and it survives any wipe.
> **`.tostr/` = generated.** The tool owns it, it is gitignored, and `parse`
> rebuilds it from scratch.

This mirrors the ecosystem: `pyproject.toml` / `ruff.toml` / `.eslintrc` live at
the root and are committed; `.mypy_cache/` / `.ruff_cache/` / `.git/` are hidden,
disposable, and gitignored.

### File layout

```
myproject/
  tostr.toml        # authored, committed   — project settings
  .tostrignore      # authored, committed   — ignore rules (mirrors .gitignore)
  .tostr/           # generated, gitignored — disposable
    cache.db        #   graph + vectors (embedding model stamped inside)
    *.log
```

Naming notes:
- `tostr.toml`, not `tostrconfig.toml` (`.toml` already implies config; compare
  `ruff.toml`).
- **Visible** (no leading dot) — the point is that users edit it; hidden files
  hurt discoverability.
- `.tostrignore` keeps its dot because it specifically mirrors `.gitignore`.
- **Config moves from `.tostr/config.toml` to the root `tostr.toml`.**

Invariant this buys us: *delete `.tostr/` and nothing authored is lost.*
`tostr clean && tostr parse` returns to a fresh build with config intact.

## 3. Command separation

### `tostr init` — scaffold project files (no parsing)

`init` is a standalone, permanent command. Its sole job is to lay down the
project's file structure so the user has something concrete to edit. It does not
parse and is **not** an alias for anything.

Responsibilities:
- Create the `.tostr/` directory (the home for generated artifacts), empty.
- Create `tostr.toml` at root, populated with defaults (commented, so the file
  documents itself).
- Create `.tostrignore` at root from the bundled language templates.
- Append `.tostr/` to the project's `.gitignore` (create it if absent).
- **Do not** parse, build the DB, or require an API key / embedding model.

Idempotency (the fix for the current bug): `init` **never clobbers** an existing
authored file. If `tostr.toml` or `.tostrignore` already exists, leave it
untouched and report it. A `--force` flag may overwrite. This makes `init` safe
to run repeatedly.

`init` is optional. Its entire purpose is to *materialize* defaults so the user
can see and edit them. A user who is happy with defaults runs `parse` directly
and never needs it.

### `tostr parse` — do the work (read config, author nothing)

Responsibilities:
- Build the AST, resolve dependencies, describe, embed, write `.tostr/cache.db`.
- **Read** config via `ProjectConfig`; **never create** `tostr.toml` or
  `.tostrignore`.
- If config files are absent, fall back to **in-code defaults** (see §5). This is
  what makes `parse` work with zero prior `init`: the user only authors files
  when they want to change something. "What was skipped by not running `init`"
  is never forced onto them as on-disk artifacts.

CLI flags (`--language`, `--no-llm`, etc.) override config for that invocation
(see precedence in §6).

> Behavioral change to note: today `tostr init` builds the database. After this
> change, the parsing work moves to `tostr parse` and `init` only scaffolds
> files. This is a deliberate, breaking redefinition of `init` — not an alias.
> Scripts or muscle memory that ran `tostr init` to build the cache must switch
> to `tostr parse`. Worth calling out in release notes.

### Why `parse` can author nothing but stay consistent with `watch`

`parse` and `watch` are **separate process invocations**. Ignore behavior is
consistent across them today *only because* `init` persisted `.tostrignore` to
disk and both rebuild `ProjectConfig` from it. If `parse` used in-memory defaults
and wrote nothing, a later `watch` (fresh process, no file on disk) would apply
only `HARDCODED_IGNORES` and, e.g., stop ignoring `venv/` — diverging from
`parse`.

The fix is **not** "make `parse` write the file." It is to move the default
ignore rules *into `ProjectConfig` as a base layer* (§5), so both processes
reconstruct identical defaults regardless of whether `.tostrignore` exists.

## 4. `tostr.toml` schema

Settings are grouped by domain. Everything has a default; nothing here is
strictly required.

```toml
# tostr.toml — Tostr project configuration. Safe to commit.

[project]
# "auto" parses every supported language, routed per-file by extension.
language = "auto"            # "auto" | "python" | "java" | ...

[llm]
# Description generation. "none" skips LLM entirely (embeddings fall back to
# code context); equivalent to the --no-llm flag.
strategy = "gemini"         # "gemini" | "none"

[embedding]
# NOTE: bound to the data on disk. Changing this invalidates every stored
# vector — it is enforced as a cache invariant, not a soft preference (see §7).
model = "all-MiniLM-L6-v2"

[graph]
# Dependency-graph scoping. Both must match between parse and watch.
include = []                # globs; empty = everything not excluded
exclude = []                # globs

# NOTE: presentation preferences (pretty-printing, color, verbosity) deliberately
# do NOT live here. They are personal, not data-bound, and would create churn in
# a shared committed file. They belong to a future user-level config
# (~/.config/tostr/config.toml) or remain CLI-flag-only. See §6.
```

### Domain rationale

| Setting          | Bound to                                | Bucket          |
|------------------|-----------------------------------------|-----------------|
| `language`       | What is parsed/stored; parse & watch must agree | project config |
| `llm.strategy`   | Descriptions (text; tolerant if mixed)  | project config  |
| `embedding.model`| The vectors in `cache.db`               | **cache invariant** (§7) |
| `graph.*`        | What edges are stored; parse & watch must agree | project config |
| pretty / color   | Display only; per-user, per-invocation  | user pref / CLI |

The split is by **ownership and lifecycle**, not by "required vs optional" —
that line is too blurry to organize files around.

## 5. `ProjectConfig` as the single merge point

`ProjectConfig` becomes the one place that resolves all layers, and both `parse`
and `watch` build it identically — guaranteeing parity.

### Ignore rules: defaults become a code layer

Today `_write_default_ignore` physically copies `languages/*/default.tostrignore`
into the user's repo. Instead, promote those templates to a **default layer
applied inside `ProjectConfig`**, exactly like `HARDCODED_IGNORES` already are.

Resulting layering (first match per gitignore semantics, later layers can negate
earlier ones with `!pattern`):

```
HARDCODED_IGNORES            (always; .git/, __pycache__/, *.pyc, .tostr/, ...)
  + bundled language defaults  (venv/, target/, ... — for the active language(s))
  + user .tostrignore          (root; additions and negations)
```

Consequences:
- `parse` with no `init` → defaults apply, nothing written, and `watch` sees the
  *same* defaults because it builds the same `ProjectConfig`. Parity holds.
- `init` → *materializes* the default layer into `.tostrignore` so the user can
  see and edit it.
- A user can remove a default by negating it (`!venv/`) since their layer is
  applied last.

### TOML config: read from root, fall back to in-code defaults

```python
class ProjectConfig:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.toml_config = self._load_toml(project_path)       # {} if absent
        self.ignore_rules = self._build_ignore_spec(project_path)  # layered, see above

    # Accessors return in-code defaults when the key/file is absent, so a missing
    # tostr.toml behaves identically to a default-valued one.
    @property
    def language(self) -> str:
        return self.toml_config.get("project", {}).get("language", "auto")

    @property
    def llm_strategy(self) -> str:
        return self.toml_config.get("llm", {}).get("strategy", "gemini")

    @property
    def embedding_model(self) -> str:
        return self.toml_config.get("embedding", {}).get("model", DEFAULT_EMBED_MODEL)

    @property
    def graph_include(self) -> list[str]:
        return self.toml_config.get("graph", {}).get("include", [])

    @property
    def graph_exclude(self) -> list[str]:
        return self.toml_config.get("graph", {}).get("exclude", [])

    def _load_toml(self, project_path: Path) -> dict:
        # Root tostr.toml. (Optionally walk parent dirs — see §9.)
        toml_path = project_path / "tostr.toml"
        if toml_path.exists():
            with open(toml_path, "rb") as f:
                return tomllib.load(f)
        return {}
```

Defaults live in **one** place (these accessors / module constants), so "no file"
and "file with defaults" are indistinguishable to every caller.

## 6. Precedence

Define it now even though the user-level file lands later:

```
in-code defaults  <  user config (~/.config/tostr)  <  project tostr.toml  <  env  <  CLI flags
```

The domains barely overlap, so conflicts are rare by construction:
- project config never sets presentation prefs;
- user config never sets data-bound settings (language, embedding model, graph).

## 7. Embedding model is a cache invariant, not a preference

Changing the embedding model invalidates every vector already in `cache.db`
(mixed embedding spaces → meaningless distances). This is the same class of
problem as a breaking format change, and the machinery already exists in
`cache_version.py` (`CACHE_FORMAT_HISTORY`, `incompatibility_reason`).

Design:
- **Stamp** the embedding model used to build the DB into the cache (a `meta`
  row, alongside or analogous to `PRAGMA user_version`).
- On any read/use command and at the start of `parse`, compare the configured
  `embedding.model` against the stamp. On mismatch, refuse to operate and emit a
  clear "embedding model changed (X → Y); run `tostr parse` to rebuild" message —
  identical UX to the existing breaking-change path, which auto-wipes and
  rebuilds on `init`/`parse`.

This keeps `embedding.model` configurable without allowing silent corruption.

## 8. `clean` behavior change

Under the authored-vs-generated split, `clean` must wipe **only** generated
state:

- Remove `.tostr/` (cache, logs, stamps).
- **Never** touch `tostr.toml` or `.tostrignore` — they are the user's source of
  truth, not cache.

Today `clean_db` unlinks `.tostrignore`; that line is removed. A separate,
opt-in `--purge` may delete authored config for users who truly want a reset.

## 9. Future-friendly (out of scope, enabled by this layout)

- **Upward discovery:** because `tostr.toml` is at the root, `ProjectConfig` can
  later walk parent directories (like git/eslint) so commands work from a
  subdirectory. Impossible if config is buried in a `.tostr/` next to the CWD.
- **User-level config:** `~/.config/tostr/config.toml` slots into the precedence
  chain (§6) with no change to the project schema.

## 10. Summary of changes

| Area | Before | After |
|------|--------|-------|
| Config location | `.tostr/config.toml` | root `tostr.toml` (visible) |
| Config creation | side effect of `init`/parse | only `init`, idempotent, never clobbers |
| `init` | parses + builds DB + writes config | scaffolds files only (`.tostr/`, `tostr.toml`, `.tostrignore`); no parsing |
| Parsing | `init` | `parse` (new command) |
| Default ignores | copied into repo | layered in `ProjectConfig`; `init` materializes |
| Missing config | partially written on the fly | in-code defaults, nothing authored |
| Embedding model | implicit | stamped + enforced as cache invariant |
| `clean` | deletes `.tostr/` + `.tostrignore` | deletes `.tostr/` only |
| `.gitignore` | manual | `init` appends `.tostr/` |
```
