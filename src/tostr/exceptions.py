from __future__ import annotations

class TostrError(Exception):
    """Base exception for all Tostr domain errors."""
    pass

class APIKeyError(TostrError):
    pass

class DatabaseNotFoundError(TostrError):
    pass
