"""Bundled scaffold templates shipped inside the package.

Loaded at runtime via ``importlib.resources`` (see ``tostr.agents._read_template``)
so it works whether Tostr is installed as a wheel, an editable install, or run from
source. This is the intended future home for the other bundled scaffolds too
(default ``tostr.toml`` / ``.tostrignore`` templates), which currently live as
in-module constants and language-dir files.
"""
