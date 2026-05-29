# Insights for Implementing Dependency Resolution in Toaster

This document captures technical insights and architectural discoveries made while implementing the Java dependency resolution system. Future implementations for C++, Go, Python, etc., should follow these patterns.

## 1. Pseudo-Type Inference via Receiver Tracking
The single most important discovery was that **full type inference is not necessary** for high-quality resolution in a structured codebase.
*   **The Pattern:** Capture method calls as `(receiver, method_name, arity)`.
*   **The Heuristic:** In the same class, look for a field or local variable named `receiver`. If found, use its declared type to resolve the method call exactly.
*   **Result:** This turns "fuzzy" method name matches into "exact" class-method matches for ~80% of calls.

## 2. Tree-Sitter Query Grouping
When capturing dependencies, use the `matches` API rather than a flat `captures` list.
*   **Why:** A single method call node might have multiple tags (e.g., `@receiver`, `@name`, `@args`). 
*   **Implementation:** Group these by match index to ensure you correctly associate the `bot` receiver with the `update()` call and not a different call in the same method.

## 3. Persistent Metadata for Partial Updates
Toaster is designed to work with a background watcher (MCP) that only parses changed files.
*   **The Challenge:** If only one file is loaded into memory, it must be able to resolve its dependencies against the rest of the project which resides in the database.
*   **Requirement:** All metadata required for resolution—specifically `dependency_names`, `inherits`, and `field_type`—**must be stored in the SQLite database**. If it's only in memory, the watcher will fail to resolve dependencies.

## 4. Inheritance-Aware Resolution
Method resolution MUST be recursive up the inheritance chain.
*   **The Pattern:** If `Class A` extends `Class B`, and `obj` is of type `A`, a call to `obj.method()` should first check `A`, then recursively check `B`.
*   **Discovery:** This requires that class inheritance itself is resolved to UIDs *before* method resolution can succeed up the chain.

## 5. Wildcard Import Expansion
Wildcards (e.g., `import .*` or `from x import *`) are common but break exact UID lookups.
*   **Strategy:** Treat wildcard imports as a "Search Pool". When a name is unresolved, query the `Registry` (and the DB) for all classes belonging to that package prefix and check them as potential parents for the missing method or type.

## 6. The "Mutation During Iteration" Trap
Recursive dependency resolution often triggers "lazy loading" from the database.
*   **The Discovery:** Calling `get_struct_by_uid` while iterating over a class's children can add new nodes to the registry, causing a `Set changed size during iteration` crash.
*   **Fix:** Always iterate over a copy of children sets (`list(self.children.values())`) during the resolution phase.

## 7. Naming Similarity Heuristics
When specific type information is missing, naming conventions provide a strong fallback.
*   **Heuristic:** If a receiver named `asm` is used, and you have fuzzy candidates in classes `ArmFSM` and `Bot`, prioritize `ArmFSM` because the receiver name is a substring or abbreviation of the class name.

## 8. Language-Specific Query Coverage
Beyond method calls, the following must be captured to build a useful graph:
*   **Object Creations:** `new Type()` (essential for connecting logic flow).
*   **Static Access:** Constants and static methods.
*   **Field Declarations:** To enable the receiver-based resolution mentioned in Insight #1.
