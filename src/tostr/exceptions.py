from __future__ import annotations

class TostrError(Exception):
    """Base exception for all Tostr domain errors."""
    pass

class APIKeyError(TostrError):
    pass

class ConfigError(TostrError):
    """Invalid or unresolvable configuration (e.g. an unknown [llm].strategy)."""
    pass

class DatabaseNotFoundError(TostrError):
    pass

class CacheFormatError(TostrError):
    """The on-disk cache format is incompatible with this build (see core.cache_version)."""
    pass
