from __future__ import annotations
import importlib.metadata

try:
    __version__ = importlib.metadata.version("tostr")
    # If running locally in dev mode without a tag, setuptools-scm automatically 
    # creates a local suffix version like "0.1.1.dev5+g1a2b3c4"
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown"