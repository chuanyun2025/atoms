"""Architectural boundary and layer dependency tests (FR-032 / AC-032)."""

import ast
import importlib

import atoms

ALLOWED_LAYER_IMPORTS: dict[str, set[str]] = {
    "core": {"core"},
    "skills": {"skills"},
    "billing": {"core", "billing"},
    "gateway": {"core", "gateway"},
    "domains": {"core", "domains"},
    "runtime": {"core", "billing", "gateway", "domains", "skills", "runtime"},
}

SUBPACKAGES = frozenset(ALLOWED_LAYER_IMPORTS)


def _imported_atoms_layers(py_file) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    layers: set[str] = set()
    pkg = py_file.parent.name
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "atoms" and len(parts) > 1 and parts[1] in SUBPACKAGES:
                    layers.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 1 and pkg in SUBPACKAGES:
                layers.add(pkg)
            elif node.level == 0 and node.module:
                parts = node.module.split(".")
                if parts[0] == "atoms":
                    if len(parts) > 1 and parts[1] in SUBPACKAGES:
                        layers.add(parts[1])
                    else:
                        for alias in node.names:
                            if alias.name in SUBPACKAGES:
                                layers.add(alias.name)
    return layers


def test_subpackage_layers_respect_acyclic_dag():
    root = atoms.PACKAGE_ROOT
    for layer, allowed in ALLOWED_LAYER_IMPORTS.items():
        layer_dir = root / layer
        assert layer_dir.is_dir(), f"Missing domain package: {layer}"
        for py_file in sorted(layer_dir.glob("*.py")):
            deps = _imported_atoms_layers(py_file)
            forbidden = deps - allowed
            assert not forbidden, (
                f"{py_file.relative_to(root)} in layer '{layer}' imports forbidden layer(s): {sorted(forbidden)}"
            )


def test_provider_gateway_remains_isolated_from_database_and_billing():
    gateway_entry = atoms.PACKAGE_ROOT / "provider_gateway.py"
    deps = _imported_atoms_layers(gateway_entry)
    assert deps <= {"gateway"}, f"provider_gateway.py must only import gateway layer, got {sorted(deps)}"


def test_process_entrypoints_and_worker_alias_remain_compatible():
    main_mod = importlib.import_module("atoms.main")
    gateway_mod = importlib.import_module("atoms.provider_gateway")
    ops_mod = importlib.import_module("atoms.ops")
    root_worker = importlib.import_module("atoms.worker")
    runtime_worker = importlib.import_module("atoms.runtime.worker")

    assert hasattr(main_mod, "app")
    assert hasattr(gateway_mod, "create_app")
    assert hasattr(ops_mod, "CURRENT_SCHEMA")
    assert root_worker is runtime_worker
