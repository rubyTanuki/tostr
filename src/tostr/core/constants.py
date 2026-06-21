from __future__ import annotations

# Name of the committed description lockfile at the project root. This is a third file category
# alongside the committed authored config (tostr.toml / .tostrignore) and the gitignored .tostr/
# cache: *generated-but-committed*. One person parses (paying the LLM cost once) and commits this
# file; everyone else's first `tostr parse` seeds descriptions from it instead of re-calling the LLM.
#
# Lives in this dependency-free module so both tostr.commands (which writes it via `tostr export`)
# and tostr.core.registry (which reads it via apply_lockfile) can import it without an import cycle.
LOCKFILE_NAME = "tostr.lock.json"

# Schema version of the lockfile itself (independent of the cache format version stamped into the
# db). Bump only on a breaking change to the lockfile's own structure.
LOCKFILE_VERSION = 1
