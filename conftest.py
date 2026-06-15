"""Root pytest config: gate integration tests behind an opt-in flag.

By default `pytest` skips anything marked `@pytest.mark.integration` (these build a
real DB, load the embedding model, and run the live file watcher). Pass
`pytest --integration` to run the full suite including them.
"""
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="also run integration tests (real DB build, embedding model, file watcher)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--integration"):
        return
    skip = pytest.mark.skip(reason="integration test; pass --integration to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
