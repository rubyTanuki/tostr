# Failproofing the Incremental AST Updater

**Status:** in progress (started 2026-06-16)
**Owner:** Avery
**Why this matters:** the save-time incremental update loop is Tostr's core moat vs graphify. It must be ironclad — after *any* sequence of edits, the cached graph must be indistinguishable from a full re-parse.

---

## The definition of "done" (the golden invariant)

The updater is failproof when, for any starting project and any sequence of file edits
(add / modify / rename-member / remove-member / rename-file / delete-file / move-file),
the incrementally-updated DB is **structurally identical** to a full `tostr init` re-parse of
the final state — modulo descriptions/vectors, which are allowed to lag but never to dangle.

Concrete integrity invariants that must hold after every update:

1. **No dangling edges** — every `edges.source_id` and `edges.target_id` exists in `structs`.
2. **No orphan structs** — every non-root struct has exactly one `is_child_of` edge to a parent that exists.
3. **No orphan vectors** — every `vec_structs.struct_id` exists in `structs`.
4. **No ghosts** — a struct removed from source has no row in `structs`, `edges` (either direction), or `vec_structs`.
5. **Stable identity** — a cosmetic edit that doesn't change a symbol's resolution identity must not change its `id`, and must not churn any inbound edge.

The acceptance test is a **golden-equivalence fuzz test** (Phase 8): apply random edits, diff
`incremental.db` against `full_reparse.db`. Anything that's not description/vector content must match.

---

## Phase 0 — Lock the UID contract  ✳️ do first

Identity is the foundation everything else builds on; nail the definition before touching code.

- [ ] Rewrite §0 of `.skills/Creating_New_Language_Parser.md` with the **overload-key** framing:
      the parenthetical suffix carries exactly what disambiguates same-named callables and nothing else.
  - Python (no overloading): `file#Class.method(...)` — literal `(...)`, no params.
  - Java (overloading): `file#Class.method(int, java.lang.String)` — ordered param **types**, no names, no return.
- [ ] Fix the contradictory examples currently in §0 (they show param names *and* types incl. `self`).
- [ ] State the new rules: field vs method disambiguated by presence of `(...)`; the parenthetical is
      deterministic (reconstructable) so logical-name → method translation can append it.

**Exit:** §0 reads as the single source of truth; both language sections below implement it verbatim.

---

## Phase 1 — Identity scheme (stable ids)

Goal: cosmetic signature edits stop churning ids. This alone removes ~90% of the inbound-edge problem.

- [x] **Python builder** (`languages/python/builders.py`): method uid → `file#Class.method(...)`.
      Drop param names from the uid entirely; `arity` kept as a field (metadata), not in identity. (2026-06-16)
- [x] **Java builder** (`languages/java/builders.py`): method uid → normalized param **types** via
      `_normalize_java_param_type` (display signature kept separate/truncated). (2026-06-16)
- [x] **Java type normalization** (`_normalize_java_param_type` + `_strip_java_package` in the Java builder,
      2026-06-16): generics erased (`List<String>`→`List`), varargs→array (`String...`→`String[]`), whitespace
      collapsed, no truncation, **and package qualifiers stripped to the simple/inner-class name**
      (`java.lang.String`→`String`, `com.example.User`→`User`, `java.util.Map.Entry`→`Map.Entry`). Chose
      package-*stripping* over FQN-*expansion*: a method is declared once so its UID is self-consistent; the
      only win is spelling-stability under respelling edits, and stripping achieves that with no import map and
      handles same-package/wildcard cases that expansion can't. Accepted limitation (rare): two distinct
      same-simple-name types from different packages collapse — only bites FQN-in-source overloading on
      identically-named classes. Done at build time because the overload key is part of the UID (the resolver
      runs after UIDs exist, so it can't influence identity).
- [ ] **Logical-name translation** (`registry._resolve_logical_name`): try `remainder` then
      `remainder + "(...)"` so Python methods resolve directly (optional cleanup, now possible).
- [ ] **Migration**: bump a DB/schema version marker; require `tostr init` re-parse (old `(self, rate)`
      rows would otherwise orphan). Document in release notes.
- [ ] Document `@typing.overload` stub collapse as accepted in `languages/python/dependency_patterns.md`.
- [ ] Add uid-format unit tests (param rename → stable Python id; `process(int)` vs `process(String)` distinct Java ids).

**Exit / tests:** uid-format unit tests per language; assert a param rename leaves the method `id` unchanged
(Python) and that `process(int)` / `process(String)` get distinct ids (Java).

---

## Phase 2 — Diff-based cache sync (kills orphans + detachment)  ⛔ core

Today `save_to_cache` only `INSERT OR REPLACE`s parsed structs and deletes edges by parsed source_id —
removed members and their edges/vectors leak forever. Single-file reparse also drops the file's
parent-directory edge.

- [x] Extended `save_to_cache(stale, prune_paths=...)` with `_prune_file_path`: after writing the parsed
      structs, deletes anything stored under the file path but absent from this parse, from `structs`,
      `edges` (**both** directions), and `vec_structs`. (All structs in a file share `path = str(rel_path)`,
      so the scope query is just `WHERE path = ?` — no LIKE needed.) Full re-parses pass no `prune_paths`.
      (`registry.py`, 2026-06-17)
- [x] Fixed **parent-directory detachment**: `parser._attach_parent_directory` walks the file's ancestor
      dirs — existing dirs are *stubbed* (edge target id only, never overwritten, so directory descriptions
      are safe), missing dirs (file saved into a new folder) are created+persisted with their own parent edge.
- [x] Capture the re-resolution worklist for Phase 4: `_prune_file_path` records dependents
      (`source_id` of `depends_on%` edges into removed structs) into `registry.inbound_reresolve_worklist`
      *before* deleting those edges. Phase 4 consumes this set.
- [x] `process_single_file` guards against pruning when nothing parsed (`registry.root is None`) so an
      unsupported/empty parse can't wipe a path; passes `prune_paths=[rel_file_path]` on both writes.

**Exit / tests:** ✅ `tests/test_watch_live_update.py` extended (4 new integration tests): removed-method
purge (struct+vector+edges), renamed-method drops old identity, file keeps its parent `is_child_of` edge
after update, and removing a depended-on class cleans the cross-file caller edge (no dangling). Added a
reusable `assert_graph_integrity` helper (no dangling edges, no orphan vectors) — an early seed of the
Phase 8 integrity checker. Full suite: 50 passed (incl. `--integration`).

---

## Phase 3 — Deletion handling

`watch_async` logs `Change.deleted` but still routes it through `process_single_file`, which throws on the
missing file and removes nothing.

- [x] Routed `Change.deleted` in `watch_async` to a dedicated `process_file_deletion` (no longer funneled
      through `process_single_file`, which used to throw on the missing file and remove nothing).
- [x] `Registry.delete_path_subtree(path_str)` purges every struct at the path or beneath it
      (`path = ? OR path LIKE ? || '/%'`), plus edges (both directions) and vectors. Shared teardown lives in
      `_delete_struct_ids` (used by both prune and delete); deleting inbound edges is what prevents dangling
      references — dependents simply re-form their edge on their own next reparse (see Phase 4). (`registry.py`)
- [x] Directory deletion cascades via the path-prefix match (one code path handles file *and* dir removal).
- [x] Rename/move = `deleted(old)+added(new)`: handled by the two independent watcher events
      (added → `process_single_file`, deleted → `process_file_deletion`), keyed by distinct paths in `active_tasks`.

**Exit / tests:** ✅ 2 new integration tests — `test_deleted_file_is_purged` (subtree gone, vectors gone,
cross-file caller edge into the deleted file not dangling) and `test_directory_deletion_cascades` (whole
`services/` subtree purged). Full suite 52 passed (incl `--integration`).

**Incidental fix:** `EmbeddingClient.queue` is now created in `start()` instead of `__init__`. The client is
a process-wide `lru_cache` singleton, so a queue built at construction stayed bound to the first event loop
and raised "bound to a different event loop" on later runs under a fresh loop (each watcher reparse / per-test
loops). Pre-existing latent bug; surfaced once enough embedder-using tests ran in one process.

---

## Phase 4 — Inbound dependency policy: drop-and-heal  ✅ resolved (no re-resolution)

**Decision (2026-06-17): do NOT re-resolve dependents. Dropping the inbound edge is correct and sufficient.**
Phases 2/3 already delete inbound edges (`target_id IN removed`) so nothing dangles. We add no re-resolution
on top, and the `inbound_reresolve_worklist` scaffolding has been removed as dead weight.

Rationale (why re-resolution buys ~nothing under the Phase-1 identity scheme):
- **Python** (parameterless identity `Class.name(...)`): an `id` only changes on rename / move-to-another-class
  / delete. In every case the caller's reference genuinely no longer resolves, so dropping is *correct* and
  re-resolution would find nothing. Param/default/annotation/arity edits don't change the id at all → no edge
  is dropped in the first place. Re-resolution adds literally nothing.
- **Java** (`Class.name(types)`): rename / incompatible-type / arity changes break the caller → drop correct.
  The lone case where a dropped edge was still valid is a *compatible* type refactor (widening `int`→`long`,
  generalizing `ArrayList`→`List`), and because overloads resolve by arity (not argument-type inference),
  re-resolution would only recover a **fuzzy** edge anyway. Marginal, Java-only, and it heals on the caller's
  next save.

A dropped edge is clean *under-connection* (safe for a context engine) rather than a stale edge pointing at a
dead id. Two cases are accepted to heal on the dependent's next reparse or a full reindex (consistent with the
already-unavoidable forward-reference case below):
- a Java caller of a compatible-type refactor (loses one fuzzy edge until its next save);
- **forward references** — B references a symbol that didn't exist when B was parsed; later it's added. There's
  no edge to capture and no reverse index of unresolved call-names, so this is unsolvable incrementally and
  always required a reparse/reindex. `dependency_names` *is* persisted, so a targeted re-resolve of a *known*
  dependent is cheap — but finding *unknown* dependents is a full project scan, hence reindex territory.

**Healing model (future work, tracked here for context — NOT this phase):** a fast, silent reparse/re-resolve
that reuses committed descriptions + vectors (the AST is cheap; only descriptions/vectors are expensive). Avery
plans: git hooks that JSON-serialize the expensive artifacts into version control, a reparse on `git pull` that
repopulates from the committed artifacts without regeneration, and optionally a per-project toggle at MCP startup
or a `tostr` scheduled task / daemon interval. Folds naturally into Phase 8's "full reindex heals everything"
guarantee.

**Exit:** ✅ nothing to build. Behavior covered by Phase 2/3 tests (`test_renamed_method_drops_old_identity`,
`test_removing_depended_on_class_cleans_cross_file_edges`, `test_deleted_file_is_purged`) — all assert no
dangling edges after the drop.

---

## Phase 5 — Resolver arity robustness

Exact arity matching already drops legitimate edges for defaults/varargs (independent of incremental).

- [ ] Python: confirm name+receiver matching (arity loose) handles defaults, `*args`/`**kwargs`,
      argparse-style call sites; add regression tests.
- [ ] Java: match an arity *range* with varargs (`foo(int...)`), keep type-based overload selection.

**Exit / tests:** `def foo(self, a, b=1)` resolves from both `foo(x)` and `foo(x, y)`; varargs resolves from any arity.

---

## Phase 6 — Description carry-over via diff_hash

Leaf-only `diff_hash` (just simplified) now makes this clean. Today every save re-describes the whole file
via LLM and blanks descriptions in the window between the two cache writes.

- [ ] On reparse, if a struct's `diff_hash` (body hash) matches the stored row, carry over the existing
      description instead of re-running the LLM.
- [ ] Fix the two-phase write so existing descriptions are never blanked mid-update.

**Exit / tests:** unchanged method keeps its description with **no** LLM call; only changed members re-describe.

---

## Phase 7 — Concurrency hardening

- [ ] Serialize DB writes (single-writer queue) so a cancelled-but-in-flight `asyncio.to_thread` write
      can't land *after* its replacement and resurrect stale data.
- [ ] Guard each write to confirm the task is still the active one for its path before committing.

**Exit / tests:** rapid successive saves of one file; concurrent saves of multiple files; assert final DB == last-write state.

---

## Phase 8 — Verification & guardrails

- [ ] Add an **integrity checker** (the 5 invariants above) usable as a test assertion; consider exposing
      it as `tostr doctor`.
- [ ] **Golden-equivalence fuzz test**: random edit sequences; diff incremental DB vs full-reparse DB.
- [ ] Run on a real open-source project; verify no orphans after a live editing session.

**Exit:** golden-equivalence test passes over many random seeds; integrity checker clean on a real project.

---

## Dependency order

```
Phase 0 (contract)
   └─ Phase 1 (identity)
         └─ Phase 2 (diff-sync + detachment)  ── core
               ├─ Phase 3 (deletions)
               └─ Phase 4 (inbound re-resolution)
Phase 5 (arity)        ─ independent, can land anytime
Phase 6 (descriptions) ─ after Phase 2
Phase 7 (concurrency)  ─ after Phase 2
Phase 8 (verification) ─ last, but write the integrity checker early and run it after each phase
```

Phases 1–4 are the failproof-critical path. 5–7 are robustness/quality. 8 proves it.
