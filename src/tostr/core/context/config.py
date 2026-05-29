import tomllib
from pathlib import Path
from typing import Dict
import pathspec

from loguru import logger
        
class ProjectConfig:
    HARDCODED_IGNORES = [
        '.DS_Store',
        '*.exe',
        '*.bin',
        '*.dll',
        '*.so',
        '*.dylib',
        '*.pyc',
        '*.pyo',
        '*.pyd',
        '__pycache__/',
        '.git/',
        '.svn/',
        '.hg/',
        '.tostr/',
        '.tostrignore',
        '*.json',
        '*.md',
        '*.kts',
        '*.properties',
        '*.xml',
        '*.gradle'
    ]

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.toml_config = self._init_toml_config(project_path)
        self.ignore_rules = self._init_path_ignore(project_path)
        self.hardcoded_rules = pathspec.PathSpec.from_lines('gitignore', self.HARDCODED_IGNORES)
    
    def _init_toml_config(self, project_path: Path) -> Dict:
        toml_path = project_path / ".tostr" / "config.toml"
        if toml_path.exists():
            with open(toml_path, 'rb') as f:
                config = tomllib.load(f)
            logger.debug(f"Loaded configuration from {toml_path}")
            return config
        logger.debug("No config.toml found, using defaults.")
        return {}
    
    def _init_path_ignore(self, project_path: Path) -> pathspec.PathSpec:
        ignore_path = project_path / ".tostrignore"
        if ignore_path.exists():
            with open(ignore_path, 'r') as f:
                return pathspec.PathSpec.from_lines('gitignore', f)
        return pathspec.PathSpec.from_lines('gitignore', [])

    def is_ignored(self, file_path: Path) -> bool:
        # 1. Convert to a POSIX string relative to the project root
        try:
            relative_path = file_path.resolve().relative_to(self.project_path.resolve()).as_posix()
        except ValueError:
            # If the file is outside the project root, we should probably ignore it
            return True

        # If it's a directory, append a slash so directory-only rules (like `dist/`) can match it
        if file_path.is_dir() and not relative_path.endswith('/'):
            relative_path += '/'

        # Check hardcoded rules first
        if self.hardcoded_rules.match_file(relative_path):
            return True

        return self.ignore_rules.match_file(relative_path)
