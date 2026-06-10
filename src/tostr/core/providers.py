from __future__ import annotations
from importlib import import_module
from loguru import logger

from tostr.exceptions import LanguageNotSupportedError

class LanguageProvider:
    # Maps language string to (package, builder_class, resolver_class)
    language_map = {
        "java": ("tostr.languages.java.builders", "JavaBuilder", "tostr.core.resolver.JavaDependencyResolver"),
        "python": ("tostr.languages.python.builders", "PythonBuilder", "tostr.core.resolver.PythonDependencyResolver"),
    }
    
    @classmethod
    def get_builder(cls, registry: "Registry") -> "BaseBuilder":
        lang = registry.language.lower()
        if lang in cls.language_map:
            package, builder_name, _ = cls.language_map[lang]
            module = import_module(package)
            builder_class = getattr(module, builder_name)
            return builder_class(registry)
        else:
            logger.error(f"No builder found for language: {lang}")
            raise LanguageNotSupportedError(f"No builder found for language: {lang}")

    @classmethod
    def get_resolver(cls, registry: "Registry") -> "BaseDependencyResolver":
        lang = registry.language.lower()
        if lang in cls.language_map:
            _, _, resolver_path = cls.language_map[lang]
            module_path, class_name = resolver_path.rsplit(".", 1)
            module = import_module(module_path)
            resolver_class = getattr(module, class_name)
            return resolver_class(registry)
        
        from tostr.core.resolver import BaseDependencyResolver
        return BaseDependencyResolver(registry)