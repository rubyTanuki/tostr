from __future__ import annotations
from collections import defaultdict
from typing import List, Dict, Optional, TYPE_CHECKING, Set
from pathlib import Path
import json
import sqlite_vec
import asyncio
from loguru import logger

from tostr.core.models import BaseFile, BaseClass, BaseMethod, BaseField, Directory
from tostr.core.db import SQLiteCache
from tostr.core.builders import BaseBuilder
from tostr.core.context.config import ProjectConfig
from tostr.core.resolver import BaseDependencyResolver

if TYPE_CHECKING:
    from tostr.core.models import BaseStruct, BaseCodeStruct
    from tostr.core.utils.progress import ProgressTracker


def _deserialize_float32(blob) -> Optional[List[float]]:
    """Inverse of sqlite_vec.serialize_float32: turn a stored vector blob back into a float list.
    Local `struct` import avoids shadowing the `struct`/`struct`-named loop vars used elsewhere."""
    if blob is None:
        return None
    import struct as _s
    return list(_s.unpack(f"{len(blob) // 4}f", blob))

class Registry:
    def __init__(self, use_cache: bool = True, db: SQLiteCache = None, project_path: Path = None, progress_tracker: "ProgressTracker" = None, config: ProjectConfig = None):
        self.progress_tracker = progress_tracker
        self.project_path = project_path
        self.use_cache = use_cache
        self.uid_map: Dict[str, BaseStruct] = {}
        self.id_map: Dict[str, BaseStruct] = {}
        self.missing_uids: Set[str] = set()
        self.missing_packages: Set[str] = set()
        self._logical_cache: Dict[str, str] = {}
        self._resolving_logicals: Set[str] = set()
        self.root: Optional[BaseStruct] = None
        self.db = db
        # A caller (e.g. parse) can inject a ProjectConfig carrying per-invocation overrides; else
        # build one from the project root so on-disk tostr.toml / .tostrignore still apply.
        self.config = config or (ProjectConfig(project_path) if project_path else None)
        self._resolvers: Dict[Optional[str], BaseDependencyResolver] = {}

    def get_resolver(self, ext: str = "") -> BaseDependencyResolver:
        from tostr.core.providers import LanguageProvider
        lang = LanguageProvider.language_for_extension(ext)
        if lang not in self._resolvers:
            self._resolvers[lang] = LanguageProvider.get_resolver(self, ext)
        return self._resolvers[lang]
    
    @property
    def language(self) -> str:
        return self.config.language if self.config else "java"

    @property
    def files(self) -> List[BaseFile]:
        return [x for x in self.uid_map.values() if isinstance(x, BaseFile)]
    
    @property
    def classes(self) -> List[BaseClass]:
        return [x for x in self.uid_map.values() if isinstance(x, BaseClass)]
    
    @property
    def methods(self) -> List[BaseMethod]:
        return [x for x in self.uid_map.values() if isinstance(x, BaseMethod)]
    
    @property
    def fields(self) -> List[BaseField]:
        return [x for x in self.uid_map.values() if isinstance(x, BaseField)]
    
    def relative_to_project(self, path: Path) -> Path:
        if not self.project_path:
            return path
        
        if not path.is_absolute():
            return path

        try:
            return path.resolve().relative_to(self.project_path.resolve())
        except ValueError:
            import os
            try:
                return path.absolute().relative_to(self.project_path.absolute())
            except ValueError:
                return Path(os.path.relpath(path.resolve(), self.project_path.resolve()))
    
    def add_struct(self, struct: BaseStruct):
        """ Adds a struct to the in-memory cache """
        self.uid_map[struct.uid] = struct
        self.id_map[struct.id] = struct

        if self.progress_tracker:
            # All structs undergo dependency resolution
            self.progress_tracker.enqueue('resolve', 1)

            # Only track describing and embedding for non-field structs
            if not isinstance(struct, BaseField):
                self.progress_tracker.enqueue('describe', 1)
                self.progress_tracker.enqueue('embed', 1)
        
    def resolve_methods(self, name: str, arity: Optional[int], parent_name: Optional[str] = None):
        if parent_name:
            if parent_name.endswith(".*"):
                package_name = parent_name[:-2]
                classes = self.get_classes_in_package(package_name)
                candidates = []
                for cls in classes:
                    candidates.extend(self._resolve_methods_recursive(cls, name, arity, set()))
                return candidates
            
            parent = self.get_struct_by_uid(parent_name)
            if parent:
                return self._resolve_methods_recursive(parent, name, arity, set())
            return []
            
        return [x for x in self.methods if x.name == name and (arity is None or x.arity == arity)]

    def _resolve_methods_recursive(self, struct: BaseStruct, name: str, arity: Optional[int], visited: set) -> List[BaseMethod]:
        if struct.uid in visited: return []
        visited.add(struct.uid)

        matches = [x for x in struct.methods if x.name == name and (arity is None or x.arity == arity)]
        if matches: return matches

        # 2. Inherited methods
        if hasattr(struct, 'inherits') and struct.inherits:
            for parent_name in struct.inherits:
                # Use the class's own resolution logic to find the parent struct
                # We use the resolver instead of model-specific resolve_type
                resolver = self.get_resolver(struct.extension)
                parent = resolver.resolve_type(struct, parent_name)
                if parent:
                    inherited_matches = self._resolve_methods_recursive(parent, name, arity, visited)
                    if inherited_matches: return inherited_matches
        
        return []

    def get_classes_in_package(self, package_name: str) -> List[BaseClass]:
        if package_name in self.missing_packages:
            return self._classes_matching_package(package_name)

        if self.use_cache and self.db:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # Dotted class UIDs (current Java builder output)
                cursor.execute(
                    "SELECT uid FROM structs WHERE type = 'class' AND (uid LIKE ? OR uid LIKE ?)",
                    (f"{package_name}.%", f"{package_name}#%")
                )
                class_uids = [row[0] for row in cursor.fetchall()]
                # Path-style UIDs: find files whose logical module path is in the package
                cursor.execute(
                    "SELECT uid FROM structs WHERE type = 'file' AND package IS NOT NULL AND package != '' AND (package = ? OR package LIKE ?)",
                    (package_name, f"{package_name}.%")
                )
                file_uids = [row[0] for row in cursor.fetchall()]

            if not class_uids and not file_uids:
                self.missing_packages.add(package_name)
            for uid in class_uids:
                self.get_struct_by_uid(uid)
            for uid in file_uids:
                self.get_struct_by_uid(uid)

        return self._classes_matching_package(package_name)

    def _classes_matching_package(self, package_name: str) -> List[BaseClass]:
        matches = []
        for cls in self.classes:
            if cls.uid.startswith((package_name + ".", package_name + "#")):
                matches.append(cls)
                continue
            pkg = self._enclosing_file_package(cls)
            if pkg and (pkg == package_name or pkg.startswith(package_name + ".")):
                matches.append(cls)
        return matches

    def _enclosing_file_package(self, struct: BaseStruct) -> str:
        node = struct
        while node is not None and not isinstance(node, BaseFile):
            node = getattr(node, "parent", None)
        return getattr(node, "package", "") if node else ""
    
    def load_filepath(self, path: Path):
        logger.debug(f"Loading subtree {str(path)}")
        path_str = str(self.relative_to_project(path))
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            if path_str != ".":
                cursor.execute("SELECT * FROM structs WHERE path = ? OR path LIKE ? || '/%'", (path_str, path_str))
            else:
                cursor.execute("SELECT * FROM structs")
                
            node_rows = cursor.fetchall()
            node_ids = [str(row["id"]) for row in node_rows]
            
            for row in node_rows:
                struct_data = dict(row)
                
                if struct_data.get("imports", None):
                    struct_data["imports"] = json.loads(struct_data["imports"])
                if struct_data.get("dependency_names", None):
                    struct_data["dependency_names"] = json.loads(struct_data["dependency_names"])
                if struct_data.get("inherits", None):
                    struct_data["inherits"] = json.loads(struct_data["inherits"])
                if struct_data.get("enum_constants", None):
                    struct_data["enum_constants"] = json.loads(struct_data["enum_constants"])
                
                builder = BaseBuilder(self)
                struct_type = struct_data["type"]
                instance = builder.with_type(struct_type=struct_type).from_dict(struct_data)
                
                if instance:
                    instance.id = str(struct_data["id"])
                    self.add_struct(instance)
            
            if not node_ids:
                return None
            
            placeholders = ",".join(["?"] * len(node_ids))
            
            if path_str == ".":
                sql = f"SELECT source_id, target_id, edge_type FROM edges WHERE edge_type = 'is_child_of'"
                cursor.execute(sql)
            else:
                sql = f"""
                    SELECT source_id, target_id, edge_type 
                    FROM edges 
                    WHERE (source_id IN ({placeholders}) 
                    OR target_id IN ({placeholders}))
                    AND edge_type = 'is_child_of'
                """
                params = node_ids + node_ids
                cursor.execute(sql, params)
            
            edge_rows = cursor.fetchall()
            
            for source_id, target_id, edge_type in edge_rows:
                source_obj = self.id_map.get(str(source_id))
                target_obj = self.id_map.get(str(target_id))
                
                if not source_obj or not target_obj:
                    continue
                
                target_obj.add_child(source_obj)
        
        self.root = self.get_struct_by_uid(path_str)
        return self.root
    
    def get_struct_by_uid(self, uid: str) -> Optional[BaseStruct]:
        if uid in self.uid_map:
            return self.uid_map[uid]

        if uid in self.missing_uids:
            return None

        if not self.use_cache or not self.db:
            return self._resolve_logical_name(uid)

        logger.debug(f"Attempting to retrieve {uid} and its children from DB")
        from tostr.core.builders import BaseBuilder
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if uid != ".":
                cursor.execute(
                    "SELECT * FROM structs WHERE uid = ? OR uid LIKE ? OR uid LIKE ? OR path = ?", 
                    (uid, f"{uid}%", f"{uid}#%", uid)
                )
            else:
                cursor.execute("SELECT * FROM structs")
            node_rows = cursor.fetchall()

            if not node_rows:
                resolved = self._resolve_logical_name(uid)
                if resolved:
                    return resolved
                self.missing_uids.add(uid)
                return None

            node_ids = [str(row["id"]) for row in node_rows]
            target_id = None
            
            for row in node_rows:
                struct_data = dict(row)
                current_id = str(struct_data["id"])
                if struct_data["uid"] == uid:
                    target_id = current_id
                
                if current_id not in self.id_map:
                    for field in ["imports", "dependency_names", "inherits", "enum_constants"]:
                        if struct_data.get(field):
                            struct_data[field] = json.loads(struct_data[field])
                    
                    builder = BaseBuilder(self)
                    instance = builder.with_type(struct_type=struct_data["type"]).from_dict(struct_data)
                    if instance:
                        instance.id = current_id
                        self.add_struct(instance)
            
            if not node_ids:
                return None
            
            placeholders = ",".join(["?"] * len(node_ids))
            sql = f"SELECT source_id, target_id, edge_type FROM edges WHERE (source_id IN ({placeholders}) OR target_id IN ({placeholders})) AND edge_type = 'is_child_of'"
            cursor.execute(sql, node_ids + node_ids)
            edge_rows = cursor.fetchall()
            
            for _source_id, _target_id, edge_type in edge_rows:
                source_obj = self.id_map.get(str(_source_id))
                target_obj = self.id_map.get(str(_target_id))
                if source_obj and target_obj:
                    target_obj.add_child(source_obj)

        return self.id_map.get(target_id) or self._resolve_logical_name(uid)

    def _resolve_logical_name(self, name: str) -> Optional[BaseStruct]:
        """Translates a dotted logical name (what source code says: 'app.services.UserService')
        into the struct at its physical path-based UID ('app/services.py#UserService').
        Imports, namespaces, and inheritance references are always dotted names, so this
        translation is required for cross-file resolution under path-based UIDs.
        The logical root of each file is its `package` field."""
        if not name or "#" in name or "/" in name or "\\" in name:
            return None
        if name in self._logical_cache:
            return self.uid_map.get(self._logical_cache[name])
        if name in self._resolving_logicals:
            return None

        self._resolving_logicals.add(name)
        try:
            # (package_length, file_uid, remainder-after-package or None for the file itself)
            candidates = []
            for f in self.files:
                pkg = getattr(f, "package", "")
                if not pkg:
                    continue
                if name == pkg:
                    candidates.append((len(pkg), f.uid, None))
                elif name.startswith(pkg + "."):
                    candidates.append((len(pkg), f.uid, name[len(pkg) + 1:]))

            if self.use_cache and self.db:
                with self.db.get_connection() as conn:
                    rows = conn.execute(
                        "SELECT uid, package FROM structs WHERE type = 'file' AND package IS NOT NULL AND package != '' AND (package = ? OR ? LIKE package || '.%')",
                        (name, name)
                    ).fetchall()
                for row in rows:
                    file_uid, pkg = row[0], row[1]
                    remainder = None if name == pkg else name[len(pkg) + 1:]
                    candidates.append((len(pkg), file_uid, remainder))

            # Longest package match wins (e.g. 'a.b' beats 'a' for 'a.b.Class')
            for _, file_uid, remainder in sorted(candidates, key=lambda c: c[0], reverse=True):
                file_struct = self.get_struct_by_uid(file_uid)
                if not file_struct:
                    continue
                target = file_struct if remainder is None else self.uid_map.get(f"{file_uid}#{remainder}")
                if target:
                    self._logical_cache[name] = target.uid
                    return target
            return None
        finally:
            self._resolving_logicals.discard(name)


    def get_struct_by_id(self, id: str) -> Optional[BaseStruct]:
        id_str = str(id)
        if id_str in self.id_map:
            return self.id_map[id_str]
            
        if not self.use_cache or not self.db:
            return None
        
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT uid FROM structs WHERE id = ?", (id_str,)).fetchone()
            if not row:
                return None
            target_uid = row[0]
            
        return self.get_struct_by_uid(target_uid)
    
    def is_stale(self, struct: BaseStruct) -> bool:
        if not self.db:
            return True
        
        return False

    def update_cached_description(self, struct: BaseStruct):
        if not self.db:
            raise RuntimeError("SqLiteCache not provided.")
        with self.db.get_connection() as conn:
            conn.execute("UPDATE structs SET description = ? WHERE uid = ?", (struct.description, struct.uid))
            conn.commit()

    def save_struct_to_cache(self, struct: BaseStruct):
        if not self.db:
            raise RuntimeError("SqLiteCache not provided.")
        
        data = struct.to_dict()
        target_uid = data.pop("uid") 
        set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
        node_sql = f"UPDATE structs SET {set_clause} WHERE uid = ?"
        node_params = list(data.values()) + [target_uid]
        
        edges = list(struct.edges)
        with self.db.get_connection() as conn:
            conn.execute(node_sql, node_params)
            conn.execute("DELETE FROM edges WHERE source_id = ?", (struct.id,))
            if edges:
                conn.executemany("INSERT INTO edges (source_id, target_id, edge_type) VALUES (?, ?, ?)", edges)
            conn.commit()

    def carry_over_unchanged(self, path_str: Optional[str] = None) -> int:
        """Reuse cached descriptions + vectors for any struct whose body is unchanged (its
        freshly-computed `diff_hash` matches the stored row), so only *changed* or *new* members pay
        the expensive regeneration cost. The describer skips LLM generation when `description` is
        already set, and the embedder skips when `vector` is set. A leaf method's hash is its own
        body; a class/file hash covers all nested text, so an edited method correctly forces its
        class and file to regenerate while untouched siblings are carried over.

        `path_str` scopes the lookup to one reparsed file (the watcher's incremental path); pass
        None to carry over across the *entire* prior cache, which is what a full `tostr parse` does
        so an unchanged project isn't re-described from scratch. Returns the number carried over."""
        if not self.db:
            return 0
        with self.db.get_connection() as conn:
            if path_str is None:
                rows = conn.execute(
                    "SELECT id, uid, diff_hash, description FROM structs"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, uid, diff_hash, description FROM structs WHERE path = ?", (path_str,)
                ).fetchall()
            prev: Dict[str, dict] = {}
            id_to_uid: Dict[str, str] = {}
            for r in rows:
                prev[r["uid"]] = {"diff_hash": r["diff_hash"], "description": r["description"] or "", "vector": None}
                id_to_uid[str(r["id"])] = r["uid"]
            if id_to_uid:
                ph = ",".join("?" * len(id_to_uid))
                for sid, vec in conn.execute(
                    f"SELECT struct_id, vector FROM vec_structs WHERE struct_id IN ({ph})", list(id_to_uid)
                ).fetchall():
                    uid = id_to_uid.get(str(sid))
                    if uid:
                        prev[uid]["vector"] = _deserialize_float32(vec)

        carried = 0
        for struct in self.uid_map.values():
            p = prev.get(struct.uid)
            if not p or not struct.diff_hash or p["diff_hash"] != struct.diff_hash:
                continue
            desc = p["description"]
            if desc.startswith("[STALE] "):  # a prior interrupted update may have left the marker
                desc = desc[len("[STALE] "):]
            if desc:
                struct.description = desc
            if p["vector"] is not None:
                struct.vector = p["vector"]
            carried += 1
        if carried:
            scope = f"under '{path_str}'" if path_str is not None else "across the project"
            logger.debug(f"Carried over {carried} unchanged struct description(s)/vector(s) {scope}")
        return carried

    def struct_exists(self, uid: str) -> bool:
        """Cheap existence check (in-memory first, then DB) — avoids the heavy hydration that
        get_struct_by_uid performs. Used when re-linking a singly-parsed file to its parent dir."""
        if uid in self.uid_map:
            return True
        if not self.db:
            return False
        with self.db.get_connection() as conn:
            return conn.execute("SELECT 1 FROM structs WHERE uid = ? LIMIT 1", (uid,)).fetchone() is not None

    def _delete_struct_ids(self, conn, ids: Set[str]) -> Set[str]:
        """Hard-delete the given struct ids and everything attached to them — edges in BOTH
        directions and vectors. Deleting inbound edges (target_id IN ids) is what keeps removed/
        renamed structs from leaving dangling references behind; those dependents simply lose the
        edge and re-form it the next time their own file is reparsed (or on a full reindex). We
        deliberately do NOT re-resolve dependents here — see the plan's Phase 4 for the rationale
        (Python's parameterless identity and Java's arity mean a dropped edge is either genuinely
        broken or only a fuzzy match anyway). Operates on the caller's connection (no commit)."""
        ids = {str(i) for i in ids}
        if not ids:
            return set()
        cur = conn.cursor()
        ph = ",".join("?" * len(ids))
        rp = list(ids)
        cur.execute(f"DELETE FROM structs WHERE id IN ({ph})", rp)
        cur.execute(f"DELETE FROM edges WHERE source_id IN ({ph})", rp)
        cur.execute(f"DELETE FROM edges WHERE target_id IN ({ph})", rp)
        cur.execute(f"DELETE FROM vec_structs WHERE struct_id IN ({ph})", rp)
        return ids

    def _prune_file_path(self, conn, path_str: str, kept_ids: Set[str]) -> Set[str]:
        """Delete structs stored under `path_str` whose id is no longer present in `kept_ids`
        (i.e. members removed/renamed out of the file on this reparse). Returns the removed ids."""
        cur = conn.cursor()
        stored = {str(r[0]) for r in cur.execute("SELECT id FROM structs WHERE path = ?", (path_str,)).fetchall()}
        removed = stored - kept_ids
        if removed:
            self._delete_struct_ids(conn, removed)
            logger.debug(f"Pruned {len(removed)} removed struct(s) under '{path_str}'")
        return removed

    def delete_path_subtree(self, path_str: str) -> Set[str]:
        """Remove a deleted file or directory from the cache entirely: every struct at `path_str`
        or beneath it (the `path LIKE '<dir>/%'` clause cascades a directory; for a single file it
        matches only that file's own structs), plus their edges and vectors. Used by the watcher's
        deletion path. Returns the removed ids."""
        if not self.db:
            raise RuntimeError("SqLiteCache not provided.")
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM structs WHERE path = ? OR path LIKE ? || '/%'",
                (path_str, path_str),
            ).fetchall()
            removed = self._delete_struct_ids(conn, {str(r[0]) for r in rows})
            conn.commit()
        if removed:
            logger.info(f"Deleted {len(removed)} struct(s) under '{path_str}' (file/dir removal)")
        return removed

    def save_to_cache(self, stale: bool = False, prune_paths: Optional[List[str]] = None):
        """Persist the in-memory structs. When `prune_paths` is given (the relative file path(s)
        being reparsed by the watcher), any struct previously stored under those paths but absent
        from this parse is deleted — this is what keeps incremental updates from leaking ghosts
        when a member is removed or renamed. Full re-parses pass no prune_paths."""
        if not self.db:
            raise RuntimeError("SqLiteCache not provided.")

        parsed_ids = [(node.id,) for node in self.uid_map.values()]
        grouped_nodes = defaultdict(list)
        all_edges = set()
        vectors = []
        
        def serialize_for_db(value):
            if isinstance(value, (dict, list, tuple, set)):
                if isinstance(value, set):
                    value = list(value)
                return json.dumps(value)
            return value
        
        for node in self.uid_map.values():
            data_dict = node.to_dict()
            if stale and data_dict.get("description"):
                data_dict["description"] = f"[STALE] {data_dict['description']}"
            
            # Extract vector if present for separate virtual table storage
            vector = data_dict.pop("vector", None)
            if vector is not None:
                vectors.append((node.id, sqlite_vec.serialize_float32(vector)))
            
            column_footprint = tuple(data_dict.keys())
            grouped_nodes[column_footprint].append(data_dict) 
            all_edges.update(node.edges)
            
        with self.db.get_connection() as conn:
            for columns_tuple, dict_list in grouped_nodes.items():
                columns = ", ".join(columns_tuple)
                placeholders = ", ".join(["?"] * len(columns_tuple))
                node_sql = f"INSERT OR REPLACE INTO structs ({columns}) VALUES ({placeholders})"
                node_values = [tuple(serialize_for_db(n.get(col)) for col in columns_tuple) for n in dict_list]
                conn.executemany(node_sql, node_values)
            
            conn.executemany("DELETE FROM edges WHERE source_id = ?", parsed_ids)
            if all_edges:
                conn.executemany("INSERT INTO edges (source_id, target_id, edge_type) VALUES (?, ?, ?)", list(all_edges))
            
            if vectors:
                # vec0 virtual tables do not naturally enforce uniqueness on non-rowid keys during REPLACE
                # so we manually delete to avoid duplicates before inserting.
                conn.executemany("DELETE FROM vec_structs WHERE struct_id = ?", [(v[0],) for v in vectors])
                conn.executemany("INSERT INTO vec_structs (struct_id, vector) VALUES (?, ?)", vectors)

            # Diff-prune: now that the freshly-parsed structs are written, remove anything that used
            # to live under these paths but is gone from this parse (deleted/renamed members).
            if prune_paths:
                kept_ids = {node.id for node in self.uid_map.values()}
                for path_str in prune_paths:
                    self._prune_file_path(conn, path_str, kept_ids)

            conn.commit()
