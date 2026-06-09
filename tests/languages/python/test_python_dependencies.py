from __future__ import annotations
import pytest
from tostr.core.registry import Registry
from tostr.languages.python.builders import PythonFileBuilder
from tostr.core.models import BaseStruct

@pytest.fixture
def registry(tmp_path):
    r = Registry(project_path=tmp_path, use_cache=False)
    # Mock config to use python
    class MockConfig:
        language = "python"
        def is_ignored(self, path): return False
    r.config = MockConfig()
    return r

def test_python_dependency_parsing(tmp_path, registry):
    """Tests that PythonMethodBuilder correctly identifies function calls."""
    python_code = """
def method1():
    method2()
    method3(1, 2)

def method2():
    pass

def method3(a, b):
    pass
"""
    path = tmp_path / "test.py"
    path.write_text(python_code)
    
    builder = PythonFileBuilder(registry)
    file_obj = builder.from_path(path)
    registry.add_struct(file_obj)

    method1 = [m for m in registry.methods if m.name == "method1"][0]
    
    # Verify dependency names and arities are parsed
    assert ("method2", 0, None, False) in method1.dependency_names
    assert ("method3", 2, None, False) in method1.dependency_names

def test_python_dependency_resolution_local(tmp_path, registry):
    """Tests resolution of local function calls (same file)."""
    python_code = """
def method1():
    method2()

def method2():
    pass
"""
    path = tmp_path / "test.py"
    path.write_text(python_code)
    
    builder = PythonFileBuilder(registry)
    file_obj = builder.from_path(path)
    registry.add_struct(file_obj)

    # Trigger resolution
    file_obj.resolve_dependencies()
    
    method1 = [m for m in registry.methods if m.name == "method1"][0]
    method2 = [m for m in registry.methods if m.name == "method2"][0]
    
    # Verify that method1 now has an outbound dependency on method2
    assert method2 in method1.outbound_dependencies

def test_python_dependency_resolution_imported(tmp_path, registry):
    """Tests resolution of function calls from imported modules."""
    python_a = """
def methodA():
    pass
"""
    python_b = """
import a
def methodB():
    a.methodA()
"""
    
    path_a = tmp_path / "a.py"
    path_a.write_text(python_a)
    path_b = tmp_path / "b.py"
    path_b.write_text(python_b)
    
    builder = PythonFileBuilder(registry)
    
    for p in [path_a, path_b]:
        file_obj = builder.from_path(p)
        registry.add_struct(file_obj)

    # Resolve all
    for file in registry.files:
        file.resolve_dependencies()
            
    method_b = [m for m in registry.methods if m.name == "methodB"][0]
    method_a = [m for m in registry.methods if m.name == "methodA"][0]
    
    assert method_a in method_b.outbound_dependencies

def test_python_dependency_resolution_instantiation(tmp_path, registry):
    """Tests resolution of class instantiations (Type resolution)."""
    python_code = """
class MyClass:
    def __init__(self, x):
        pass

def factory():
    obj = MyClass(10)
"""
    path = tmp_path / "test.py"
    path.write_text(python_code)
    
    builder = PythonFileBuilder(registry)
    file_obj = builder.from_path(path)
    registry.add_struct(file_obj)
    
    file_obj.resolve_dependencies()
    
    factory = [m for m in registry.methods if m.name == "factory"][0]
    my_class = [c for c in registry.classes if c.name == "MyClass"][0]
    
    assert my_class in factory.outbound_dependencies
