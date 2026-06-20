# `tostr export` — Version-Controlled Description Lockfile

## Goal

Let teammates onboarding onto an already-parsed project skip the expensive LLM description
pass. One person parses (paying Gemini cost once), commits a `tostr.lock.json`, and everyone
else's first `tostr parse` seeds descriptions from that file instead of re-calling the LLM.

## Core design decisions

These were settled in the design discussion; the rest of the plan implements them.

1. **Descriptions only — recompute vectors locally.** Descriptions are the only expensive
   artifact (Gemini calls, rate limits). Vectors come from the bundled local ONNX
   `all-MiniLM-L6-v2` (free, fast, no API key). Exporting vectors also bloats the file into an
   unreviewable, merge-conflict-prone blob and adds cross-platform float-determinism risk.
   `--with-vectors` is an opt-in flag for users who want literal zero recompute; **off by default.**

2. **The lockfile is a projection of the cache, refreshed where the cache changes — not on
   commit.** `parse` maintains `tostr.lock.json` automatically (like `npm install` maintains
   `package-lock.json`). There is no git pre-commit hook. `tostr export` exists as an explicit
   manual snapshot/escape hatch.

3. **Consumption is pull-based.** After a `git pull` brings in an updated lockfile, nothing
   runs automatically. The file just sits there and is consumed as a *seed* by the next
   `tostr parse` (or the MCP server's parse-on-init). No `post-checkout`/`post-merge` hook
   firing expensive, networked work behind the user's back.

4. **`(uid, diff_hash)` is the reuse key.** This is exactly what `Registry.carry_over_unchanged`
   (`registry.py:419`) already uses to reuse descriptions across reparses — both fields are
   machine-independent (`uid` is the relative path / logical name, `diff_hash` is the body hash).
   The seed is that same mechanism sourced from the lockfile instead of the live `cache.db`.

## Lockfile format

Path: `<project_root>/tostr.lock.json` — **committed** (a third file category alongside the
committed `tostr.toml` / `.tostrignore` and the gitignored `.tostr/`).

```json
{
  "tostr_lock_version": 1,
  "cache_format_version": 1,
  "entries": {
    "src/app/services.py#UserService": {
      "diff_hash": "a1b2c3d4...",
      "description": "Coordinates user lookups and persistence..."
    },
    "src/app/services.py#UserService#get_user(...)": {
      "diff_hash": "e5f6...",
      "description": "Fetches a user by id, raising NotFound..."
    }
  }
}
```

Serialization rules (git-friendliness is the whole point):
- Keyed by `uid`; `id` is omitted (derivable as `md5(uid)[:10]` with type prefix, `models.py:120`).
- `json.dumps(..., indent=2, sort_keys=True, ensure_ascii=False)` + trailing newline → stable,
  line-per-field diffs that review cleanly in a PR.
- Only structs with a **non-empty** description are written.
- **No-op write:** compare against the existing file bytes and skip the write if identical, so
  a `parse` that changed nothing doesn't churn git mtime/diffs.
- `cache_format_version` is stamped from `CURRENT_CACHE_VERSION` (`cache_version.py:49`). A
  breaking UID-scheme change would change uids anyway (no match), but the explicit guard lets
  `apply` skip a stale lockfile cleanly instead of silently no-matching.
- `--with-vectors` adds a `"vector": [float, ...]` field per entry, pulled from `vec_structs`
  (joined on the derived `id`). Default omitted.

## Implementation

### 1. `commands.py` — export (read cache → lockfile)

New `LOCKFILE_NAME = "tostr.lock.json"` module constant.

```python
def export_lockfile(target_path: Path, with_vectors: bool = False) -> dict:
    """Snapshot expensive cache artifacts (descriptions, optionally vectors) to tostr.lock.json
    for version control. Returns a small report dict (entries_written, path, changed: bool)."""
```
- `_verify_db_exists(target_path)` (reuse existing guard at `commands.py:19`).
- Open `SQLiteCache`; `SELECT uid, diff_hash, description FROM structs WHERE description IS NOT NULL AND description != ''`.
  - Skip rows whose description still carries the `[STALE] ` marker (`registry.py:546`) — never
    export a known-stale description.
- If `with_vectors`: also `SELECT struct_id, vector FROM vec_structs` and map back via
  `id`→`uid` (query `structs.id`), deserialize with the existing `_deserialize_float32`
  helper (`registry.py:21`).
- Build the dict, serialize deterministically, do the no-op-aware write.
- Return report for the CLI/MCP layer to render.

### 2. `registry.py` — seed (lockfile → in-memory structs)

New method, a sibling of `carry_over_unchanged`:

```python
def apply_lockfile(self) -> int:
    """Seed descriptions (and vectors when present) onto freshly-parsed structs from
    tostr.lock.json, matched on (uid, diff_hash). Mirrors carry_over_unchanged but sources
    from the committed lockfile instead of the live cache. Runs after resolve, before describe,
    so the describer/embedder skip every successfully-seeded struct. Returns count seeded."""
```
- Read `self.project_path / LOCKFILE_NAME`; return `0` if absent or `use_lockfile` is False.
- If `cache_format_version` is incompatible (`incompatibility_reason`), log a warning and return `0`.
- For each `struct in self.uid_map.values()`: if `entries[struct.uid].diff_hash == struct.diff_hash`
  and `struct.description` is empty → set `struct.description` (and `struct.vector` if the entry
  carries one). Identical skip logic to `carry_over_unchanged:447-459`.
- Add a `use_lockfile: bool = True` field on `Registry.__init__` so callers can opt out.

**Embedding consequence (the operative effect of descriptions-only):** seeding only a description
leaves `struct.vector = None`, so `_handle_embed` (`describer.py:25`) still enqueues it and the
struct is **re-embedded locally** — free ONNX, no API key, and deterministic: the embed input is
`f"{uid}: {description}"` (`embeddings/base.py:88`), so the recomputed vector reproduces the
author's vector (same model) and search quality is unchanged. Only the expensive Gemini call is
skipped. With `--with-vectors`, the entry also carries `vector`; setting `struct.vector` makes
`_handle_embed` skip the embed too — identical to the local `carry_over_unchanged` path, just
sourced from the lockfile. So: descriptions-only = skip the dollars, pay cheap local embed;
`--with-vectors` = skip both, at the cost of a larger, merge-noisy file.

### 3. `parser.py` — seed hook between resolve and describe

In `BaseParser.parse()` (`parser.py:24`), insert one line between `resolve_dependencies()`
(line 34) and `resolve_descriptions_async()` (line 36):

```python
self.resolve_dependencies()
self.registry.apply_lockfile()      # seed descriptions before the (expensive) describe pass
await self.resolve_descriptions_async()
```
This is the only describe path used by full `parse`; the watcher path
(`process_single_file`) does **not** go through `parse()` and already reuses the live cache via
`carry_over_unchanged` (`commands.py:430`), so it needs no change for the primary use case.
(Watcher lockfile-seeding for freshly *pulled* files is a stretch goal — see Out of Scope.)

### 4. `commands.py` — `parse_async` maintains the lockfile

At the end of `parse_async` (`commands.py:198`), after `parser.registry.save_to_cache()`
(line 226), refresh the lockfile so the producer's commit always carries up-to-date artifacts:

```python
parser.registry.save_to_cache()
if config.llm_strategy != "none" and not no_llm:
    export_lockfile(target_path)     # no-op write when unchanged
```
- Guard on LLM being active: in `--no-llm` runs there are no descriptions worth exporting, and
  we must **not** overwrite an existing teammate-provided lockfile with an empty one.
- Thread `use_lockfile` from `parse_async` into the `Registry` (via `_build_ast_async`) so a
  future `--no-lockfile` escape hatch is trivial. Seeding is on by default.

### 5. `cli.py` — `tostr export` command

Mirror the existing command shape (`clean`/`init` at `cli.py:171,205`):
```
tostr export [path] [--with-vectors] [--debug/--no-debug]
```
- `configure_cli_logging(debug)`, call `export_lockfile`, render the report
  (`✅ Wrote tostr.lock.json (N descriptions)` or `tostr.lock.json already up to date`).
- Wrap in the standard `try/except TostrError → typer.Exit(1)` pattern used by every command.

### 6. `server.py` — `export` MCP tool

Add an `@mcp.tool() async def export(workspace_path, with_vectors=False)` mirroring the `clean`
tool shape (`server.py:324`): `_resolve_workspace`, `configure_mcp_logging`, call
`export_lockfile`, return a short success string. Lower priority than the CLI command since the
MCP `parse` tool already maintains the lockfile via `parse_async`, but include it for parity and
explicit agent-driven snapshots.

> Note on MCP `parse` auto-sync (`server.py:144`): the early-return branch (cache exists +
> `use_cache`) skips `parse_async`, so it neither re-seeds nor re-exports. That's correct — a
> teammate's cold start has **no** `.tostr/cache.db` (gitignored), so it always falls through to
> `parse_async` and seeds. The early return only fires once the user already has a built cache.

### 7. Wiring / exports

- Export `LOCKFILE_NAME` and `export_lockfile` where the other command symbols are surfaced
  (`commands.py`, imported in `cli.py:15` and `server.py:16`).
- Register the new CLI command and MCP tool.

## Edge cases & failure modes

- **Lockfile present but `cache.db` absent (clean clone):** the cold-start path. `parse_async`
  builds the AST, `apply_lockfile` seeds descriptions, only genuinely-changed/new structs hit
  the LLM. This is the headline win.
- **Code diverged from lockfile:** `diff_hash` won't match → that struct regenerates. Correct
  self-healing, not a bug. Partial reuse for the unchanged majority still applies.
- **Whitespace/formatting drift on the same logical code:** `diff_hash` is byte-sensitive, so a
  reformatted-but-equivalent body regenerates. Acceptable — teammates on the same checkout are
  byte-identical; this only bites across divergent formatting, where regaining correctness is
  cheap and safe.
- **Stale markers:** never export `[STALE] …` descriptions; never seed them (mirror
  `carry_over_unchanged`'s strip at `registry.py:453`).
- **`--no-llm` parse:** does not overwrite an existing lockfile (guarded in §4).
- **Incompatible `cache_format_version`:** `apply_lockfile` warns and no-ops; user just pays a
  normal parse.
- **Merge conflicts in `tostr.lock.json`:** possible but readable (one struct per few lines).
  Resolving badly is self-correcting — a wrong/garbled description regenerates next parse if its
  `diff_hash` no longer matches, and is harmless text if it does.

## README integration

- **"Setting up Tostr" mental model** (README §137): add `tostr.lock.json` as the third file
  category — *generated-but-committed*, the AST equivalent of a lockfile — distinct from the
  committed-authored `tostr.toml`/`.tostrignore` and the gitignored `.tostr/`.
- **New `tostr export` subsection** under "Other Commands" (after `clean`, README §251): what it
  does, when you'd run it manually vs. relying on `parse`, and the `--with-vectors` flag.
- **`parse` section** (README §160): note that parse refreshes `tostr.lock.json` and seeds from
  it on cold start; commit the lockfile to share descriptions with teammates.
- **Team-onboarding blurb:** `git clone && tostr parse` reuses a teammate's descriptions for
  free (no API key needed for the unchanged majority) — the core value proposition.

## Tests

- `export_lockfile`: writes expected entries; excludes empty + `[STALE]` descriptions;
  deterministic byte-stable output; no-op write when unchanged; `--with-vectors` round-trips.
- `apply_lockfile`: seeds on `(uid, diff_hash)` match; skips on hash mismatch; skips when
  description already set; honors incompatible `cache_format_version`; absent file is a no-op.
- Integration: parse a project, export, `clean`, re-parse with a stubbed/asserted-zero LLM and
  confirm descriptions are restored from the lockfile (the onboarding scenario). Fixture:
  `tests/testcode/PythonTestProject`.
- `parse_async` refreshes the lockfile on LLM runs and leaves it untouched on `--no-llm`.

## Out of scope (note as future work)

- **Git hooks.** No producer pre-commit hook (lockfile is maintained by `parse`). At most a
  future *opt-in, notify-only* `post-merge` hook (`tostr init --with-hooks`) printing
  "🌴 tostr.lock.json changed — run `tostr parse` to sync". Hooks don't distribute via git
  (`.git/hooks` isn't versioned), so nothing automatic should depend on them.
- **Watcher lockfile-seeding** for files freshly introduced by a pull while the MCP server is
  live (would let `process_single_file` consult the lockfile alongside `carry_over_unchanged`).
- ~~Full-parse reuse from `cache.db`~~ — **fixed separately**: `BaseParser.parse()` now calls
  `Registry.carry_over_unchanged()` (whole-project scope) when `use_cache` is set, so a full
  reparse reuses the user's own cached descriptions/vectors for unchanged code. The lockfile seed
  is complementary: `carry_over_unchanged` reuses the *local* `cache.db`; `apply_lockfile` reuses
  a *teammate's committed* artifacts on a cold clone where no local cache exists. (Residual:
  `Directory` structs lack a `diff_hash` so they still re-describe — a separate enhancement.)

## Step checklist

1. `commands.py`: `LOCKFILE_NAME`, `export_lockfile()`.
2. `registry.py`: `use_lockfile` field + `apply_lockfile()`.
3. `parser.py`: seed call in `BaseParser.parse()` between resolve and describe.
4. `commands.py`: lockfile refresh + `use_lockfile` threading in `parse_async`/`_build_ast_async`.
5. `cli.py`: `export` command.
6. `server.py`: `export` MCP tool.
7. Tests (§Tests).
8. README updates (§README integration).
```
