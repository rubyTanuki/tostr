from __future__ import annotations
from collections import defaultdict
from typing import List, Dict, Optional, TYPE_CHECKING, Set
from pathlib import Path
import json
import hashlib
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

class Registry:
    def __init__(self, use_cache: bool = True, db: SQLiteCache = None, project_path: Path = None, progress_tracker: "ProgressTracker" = None):
        self.progress_tracker = progress_tracker
        self.project_path = project_path
        self.use_cache = use_cache
        self.uid_map: Dict[str, BaseStruct] = {}
        self.id_map: Dict[str, BaseStruct] = {}
        self.missing_uids: Set[str] = set()
        self.missing_packages: Set[str] = set()
        self.root: Optional[BaseStruct] = None
        self.db = db
        self.config = ProjectConfig(project_path) if project_path else None
        self._resolver = None

    def get_resolver(self) -> BaseDependencyResolver:
        if self._resolver is None:
            from tostr.core.providers import LanguageProvider
            self._resolver = LanguageProvider.get_resolver(self)
        return self._resolver
    
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
                resolver = self.get_resolver()
                parent = resolver.resolve_type(struct, parent_name)
                if parent:
                    inherited_matches = self._resolve_methods_recursive(parent, name, arity, visited)
                    if inherited_matches: return inherited_matches
        
        return []

    def get_classes_in_package(self, package_name: str) -> List[BaseClass]:
        if package_name in self.missing_packages:
            return [x for x in self.classes if x.uid.startswith(package_name + ".") or x.uid.startswith(package_name + "#")]

        if self.use_cache and self.db:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT uid FROM structs WHERE type = 'BaseClass' AND (uid LIKE ? OR uid LIKE ?)",
                    (f"{package_name}.%", f"{package_name}#%")
                )
                rows = cursor.fetchall()
                if not rows:
                    self.missing_packages.add(package_name)
                for row in rows:
                    self.get_struct_by_uid(row[0])
        
        return [x for x in self.classes if x.uid.startswith(package_name + ".") or x.uid.startswith(package_name + "#")]
    
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
            return None
        
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
                    
        return self.id_map.get(target_id)


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

    def propagate_hash_update(self, struct_uid: str):
        """Iteratively updates the distributed hashes of all ancestors of a struct in the DB."""
        if not self.db:
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Get the initial ID of the struct
            cursor.execute("SELECT id FROM structs WHERE uid = ?", (struct_uid,))
            row = cursor.fetchone()
            if not row:
                logger.debug(f"Could not find struct with UID {struct_uid} to propagate hash update.")
                return
            current_id = row[0]

            while True:
                # 2. Find the parent
                cursor.execute(
                    "SELECT target_id FROM edges WHERE source_id = ? AND edge_type = 'is_child_of'", 
                    (current_id,)
                )
                parent_row = cursor.fetchone()
                if not parent_row:
                    break
                
                parent_id = parent_row[0]
                
                # 3. Get all children's hashes for this parent
                cursor.execute("""
                    SELECT diff_hash FROM structs 
                    WHERE id IN (SELECT source_id FROM edges WHERE target_id = ? AND edge_type = 'is_child_of')
                """, (parent_id,))
                child_hashes = [r[0] for r in cursor.fetchall() if r[0]]
                
                if not child_hashes:
                    new_hash = ""
                else:
                    child_hashes.sort()
                    new_hash = hashlib.md5("".join(child_hashes).encode("utf-8")).hexdigest()
                
                # 4. Update the parent's hash
                cursor.execute("UPDATE structs SET diff_hash = ? WHERE id = ?", (new_hash, parent_id))
                
                # 5. Move up the tree
                current_id = parent_id
            
            conn.commit()

    def save_to_cache(self, stale: bool = False):
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
                
            conn.commit()
