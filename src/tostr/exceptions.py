
class TostrError(Exception):
    """Base exception for all Tostr domain errors."""
    pass

class StructNotFoundError(TostrError):
    pass

class APIKeyError(TostrError):
    pass

class ResolveError(TostrError):
    pass

class LanguageNotSupportedError(TostrError):
    pass

class TargetFileNotFoundError(TostrError):
    pass

class DatabaseNotFoundError(TostrError):
    pass