"""Unit tests for the watcher's single-writer guard (`commands._guarded_write`).

These are pure-asyncio (no DB, no embedding model) so they run in the default suite, not behind
`--integration`. They pin the concurrency guarantee: a write from a task that has been superseded
by a newer change for the same path is skipped, while the live task's write runs.
"""
from __future__ import annotations
import asyncio
from pathlib import Path

import pytest

import tostr.commands as commands


@pytest.fixture
def clean_active_tasks():
    saved = dict(commands.active_tasks)
    commands.active_tasks.clear()
    yield
    commands.active_tasks.clear()
    commands.active_tasks.update(saved)


async def test_guarded_write_runs_when_task_is_current(clean_active_tasks):
    lock = asyncio.Lock()
    fp = Path("/tmp/tostr-guard-current.py")
    calls = []

    def fake_write(tag):
        calls.append(tag)
        return f"wrote {tag}"

    commands.active_tasks[fp] = asyncio.current_task()
    result = await commands._guarded_write(lock, fp, fake_write, "v1")

    assert calls == ["v1"]
    assert result == "wrote v1"


async def test_guarded_write_skips_when_superseded(clean_active_tasks):
    lock = asyncio.Lock()
    fp = Path("/tmp/tostr-guard-superseded.py")
    calls = []

    def fake_write(tag):
        calls.append(tag)

    # This task registers, then a newer change replaces it in active_tasks.
    commands.active_tasks[fp] = asyncio.current_task()
    commands.active_tasks[fp] = object()  # supersede with a different "task"

    result = await commands._guarded_write(lock, fp, fake_write, "stale")

    assert calls == [], "a superseded task must not write"
    assert result is None


async def test_guarded_write_without_lock_always_runs(clean_active_tasks):
    """Direct callers (tests/non-watcher) pass no lock and await to completion — no guard applies."""
    fp = Path("/tmp/tostr-guard-nolock.py")
    calls = []

    def fake_write():
        calls.append(True)
        return 42

    # Even with no matching active_tasks entry, a lock-less call runs.
    result = await commands._guarded_write(None, fp, fake_write)

    assert calls == [True]
    assert result == 42


async def test_guarded_write_serializes_concurrent_writers(clean_active_tasks):
    """Two live writers on different paths run under the shared lock without overlapping."""
    lock = asyncio.Lock()
    overlap = {"current": 0, "max": 0}

    def fake_write():
        overlap["current"] += 1
        overlap["max"] = max(overlap["max"], overlap["current"])
        # Busy-ish to widen any overlap window if the lock were not held.
        for _ in range(10000):
            pass
        overlap["current"] -= 1

    async def writer(path):
        commands.active_tasks[path] = asyncio.current_task()
        await commands._guarded_write(lock, path, fake_write)

    await asyncio.gather(
        writer(Path("/tmp/tostr-a.py")),
        writer(Path("/tmp/tostr-b.py")),
        writer(Path("/tmp/tostr-c.py")),
    )

    assert overlap["max"] == 1, "writes were not serialized by the lock"
