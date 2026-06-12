# Python Dependency Patterns — Tostr Support Reference

This document enumerates all ways dependencies can be expressed in Python,
and specifies what Tostr's heuristic resolver supports or skips.

---

## Import Forms

| Pattern | Example | Supported | Notes |
|---|---|---|---|
| Simple module import | `import os` | ✅ | Stores `os` as import |
| Dotted module import | `import os.path` | ✅ | Stores `os.path` |
| Aliased module import | `import numpy as np` | ✅ | Stores `numpy`; `np` normalized to `numpy` at call sites |
| Named import | `from module import Foo` | ✅ | Stores `module.Foo` |
| Multi-name import | `from module import Foo, Bar` | ✅ | Stores `module.Foo`, `module.Bar` |
| Aliased named import | `from module import Foo as F` | ✅ | Stores `module.Foo`; `F` normalized to `module.Foo` at call sites |
| Wildcard import | `from module import *` | ✅ | Stores `module.*`; calls resolved via fuzzy matching |
| Relative import (1 level) | `from . import foo` | ✅ | Resolved against current package |
| Relative import (n levels) | `from .. import bar` | ✅ | Resolved against n-level parent |
| Relative submodule import | `from .utils import helper` | ✅ | Fully resolved to absolute module path |

---

## Call / Dependency Invocation Forms

| Pattern | Example | Supported | Notes |
|---|---|---|---|
| Direct function call (same file) | `foo()` | ✅ | Local search in same scope |
| `self.method()` call | `self.process()` | ✅ | `self` resolved to parent class |
| `cls.method()` call | `cls.create()` | ✅ | `cls` resolved to parent class |
| Inherited method via `self` | `self.base_method()` | ✅ | Traverses inheritance chain |
| Imported class instantiation | `MyClass()` after `from m import MyClass` | ✅ | Falls back to type resolution |
| Imported function call | `helper()` after `from utils import helper` | ✅ | Found via import lookup |
| Module-level call | `module.func()` after `import module` | ✅ | Receiver `module` matched to import |
| Aliased call | `F()` after `from m import Foo as F` | ✅ | Normalized to `m.Foo` before resolution |
| Aliased module call | `np.array()` after `import numpy as np` | ✅ (partial) | Receiver normalized; only resolves if target is in-project |
| `self.field.method()` (1 level) | `self.client.post()` | ✅ | Requires type annotation on field |
| Inheritance declaration | `class Child(Parent):` | ✅ | Parent added as class-level dependency |
| Field type annotation dependency | `manager: SomeClass` | ✅ | Type extracted from annotation |

---

## Unsupported Patterns (documented for users)

| Pattern | Example | Why skipped |
|---|---|---|
| Local variable type inference | `foo = Bar(); foo.method()` | Requires data-flow analysis; `foo` not a class field |
| Instance variable from `__init__` | `self.x = MyClass()` in `__init__` | Assignment in method body, no type annotation |
| Multi-level chained access | `self.a.b.c()` | Only one level beyond `self` is resolved |
| Dynamic dispatch via `getattr` | `getattr(obj, name)()` | Dynamic; not resolvable statically |
| `*args` / `**kwargs` spread calls | `func(*args)` | Spread args not counted toward arity |
| Subscript receiver | `items[0].method()` | AST receiver is subscript, not in query pattern |
| Protocol / ABC structural subtyping | `def foo(x: Drawable): x.draw()` | Parameter type resolution not implemented |
| Lambda captures | `sorted(x, key=lambda i: i.val)` | Captured deps inside lambdas may not resolve |
| `super()` calls | `super().__init__()` | `super()` receiver does not map to parent class via heuristic |

---

## Arity Handling

- `self` and `cls` are **excluded** from method arity counts.
  - `def foo(self, a, b)` → `arity = 2`
- Python uses **soft arity matching** (`strict_arity = False`):
  - Arity is not used during resolution lookups; all methods with the matching name are candidates.
  - This handles default args, `*args`, keyword-only args, etc.

---

## Notes on Wildcard Imports

`from module import *` stores `module.*`. During resolution, Tostr will look up all
classes in the `module` namespace when searching for a matching method. This can produce
multiple fuzzy candidates if several classes share a method name — those are stored as
`outbound_dependencies_fuzzy` rather than `outbound_dependencies`.
