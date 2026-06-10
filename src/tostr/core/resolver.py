from __future__ import annotations
from typing import TYPE_CHECKING, Optional, List, Tuple, Set
from loguru import logger

if TYPE_CHECKING:
    from tostr.core.models import BaseStruct, BaseFile, BaseClass, BaseMethod, BaseField
    from tostr.core.registry import Registry

class BaseDependencyResolver:
    def __init__(self, registry: Registry):
        self.registry = registry
        self.strict_arity = True

    def resolve_type(self, scope: BaseStruct, type_name: str) -> Optional[BaseStruct]:
        """Resolves a simple or scoped type name to a struct using imports and package info."""
        if not type_name: return None
        
        # 1. Exact match (already a UID)
        dep = self.registry.get_struct_by_uid(type_name)
        if dep: return dep
        
        # 2. Scope-specific resolution (e.g. same package/module)
        # We try to prefix with the scope's namespace if applicable
        namespace = self._get_namespace(scope)
        if namespace:
            dep = self.registry.get_struct_by_uid(f"{namespace}.{type_name}")
            if dep: return dep

        # 3. Imports
        imports = getattr(scope, "imports", [])
        if not imports and scope.parent:
            imports = getattr(scope.parent, "imports", [])
            
        for imp in imports:
            # Specific imports
            if imp.endswith(f".{type_name}"):
                dep = self.registry.get_struct_by_uid(imp)
                if dep: return dep
            
            # Wildcard imports (e.g. java .* or python *)
            if imp.endswith(".*"):
                prefix = imp[:-2]
                dep = self.registry.get_struct_by_uid(f"{prefix}.{type_name}")
                if dep: return dep
            elif imp.endswith("*"): # Support for python-style wildcards if normalized this way
                prefix = imp[:-1]
                if not prefix.endswith("."): prefix += "."
                dep = self.registry.get_struct_by_uid(f"{prefix}{type_name}")
                if dep: return dep
        
        return None

    def resolve_method_dependencies(self, method: BaseMethod):
        """Resolves dependencies for a given method/function."""
        # logger.debug(f"Resolving dependencies for method {method.uid}")
        
        for dep_info in method.dependency_names:
            if len(dep_info) == 2:
                name, arity = dep_info
                receiver, is_creation = None, False
            else:
                name, arity, receiver, is_creation = dep_info

            if is_creation:
                dep = self.resolve_type(method.parent or method, name)
                if dep: method.add_dependency(dep)
                continue

            # --- METHOD RESOLUTION ---
            resolved = False
            
            # 1. LOCAL SEARCH (Same container)
            search_scope = method.parent.children if method.parent else method.children
            for child_set in list(search_scope.values()):
                for child in list(child_set):
                    if child.name == name and (not self.strict_arity or getattr(child, "arity", -1) == arity):
                        method.add_dependency(child)
                        resolved = True
                        break
                if resolved: break
            if resolved: continue

            # 2. RECEIVER-BASED HEURISTIC
            if receiver:
                receiver_type = self._resolve_receiver_type(method, receiver)
                if receiver_type:
                    dep_type = self.resolve_type(method.parent or method, receiver_type)
                    if dep_type:
                        lookup_arity = arity if self.strict_arity else None
                        candidates = self.registry.resolve_methods(name=name, arity=lookup_arity, parent_name=dep_type.uid)
                        if candidates:
                            method.add_dependency(candidates[0])
                            continue
            
            # 3. IMPORTED & INHERITED
            potential_parents = self._get_potential_lookup_parents(method)
            all_candidates = []
            lookup_arity = arity if self.strict_arity else None
            for p_name in potential_parents:
                candidates = self.registry.resolve_methods(name=name, arity=lookup_arity, parent_name=p_name)
                all_candidates.extend(candidates)
            
            if len(all_candidates) == 1:
                method.add_dependency(all_candidates[0])
            elif not all_candidates:
                # 4. TYPE RESOLUTION (Class instantiation or Type reference)
                dep = self.resolve_type(method.parent or method, name)
                if dep:
                    method.add_dependency(dep)
            elif len(all_candidates) > 1:
                # Apply heuristic: if receiver matches part of class name
                refined_candidates = []
                if receiver:
                    for c in all_candidates:
                        if receiver.lower() in c.parent.name.lower():
                            refined_candidates.append(c)
                
                if len(refined_candidates) == 1:
                    method.add_dependency(refined_candidates[0])
                else:
                    for c in all_candidates:
                        method.add_fuzzy_dependency(c)

    def _get_namespace(self, scope: BaseStruct) -> Optional[str]:
        """Gets the namespace (package/module) for a given scope."""
        # Check for 'package' attribute (Java style)
        if hasattr(scope, 'package') and scope.package:
            return scope.package
        if scope.parent and hasattr(scope.parent, 'package') and scope.parent.package:
            return scope.parent.package
            
        # Fallback to parent UID if it looks like a namespace
        # We check class name to avoid circular imports with Directory
        if scope.parent and scope.parent.__class__.__name__ not in ("Directory", "Root"):
             return scope.parent.uid
        return None

    def _resolve_receiver_type(self, method: BaseMethod, receiver: str) -> Optional[str]:
        """Attempts to find the type of a receiver (e.g. a variable or field)."""
        # 1. Check parent fields (Class fields or Module globals)
        if method.parent:
            for field in method.parent.fields:
                if field.name == receiver:
                    return field.field_type
        
        # 2. Check if receiver matches an import (Module-based calls)
        parent = method.parent
        imports = getattr(parent, "imports", [])
        if not imports and parent and parent.parent:
            imports = getattr(parent.parent, "imports", [])
            
        # print(f"DEBUG: resolving receiver '{receiver}' against imports: {imports}")
        for imp in imports:
            if imp == receiver or imp.endswith(f".{receiver}"):
                return imp

        # 3. Check method parameters (TODO)
        
        return None

    def _get_potential_lookup_parents(self, method: BaseMethod) -> List[str]:
        """Gets a list of UIDs or wildcards where we should look for methods."""
        parent = method.parent
        if not parent: return []

        # Check cache if it's a class
        if hasattr(parent, '_potential_parents_cache') and parent._potential_parents_cache is not None:
            return parent._potential_parents_cache

        potential_parents = []
        
        # Same namespace
        namespace = self._get_namespace(method)
        if namespace:
            potential_parents.append(f"{namespace}.*")
        
        # Imports
        imports = getattr(parent, "imports", [])
        if not imports and parent.parent:
            imports = getattr(parent.parent, "imports", [])
        potential_parents.extend(imports)
        
        # Inheritance
        if hasattr(parent, "inherits"):
            potential_parents.extend(parent.inherits)

        # Cache it if it's a class
        if hasattr(parent, '_potential_parents_cache'):
            parent._potential_parents_cache = potential_parents
            
        return potential_parents

class JavaDependencyResolver(BaseDependencyResolver):
    """Specific tweaks for Java if necessary."""
    pass

class PythonDependencyResolver(BaseDependencyResolver):
    """Specific tweaks for Python if necessary."""
    def __init__(self, registry: Registry):
        super().__init__(registry)
        self.strict_arity = False
