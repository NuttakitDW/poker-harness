"""Transitive local-source and native dependency fingerprints."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parent
VOICE_DIR = ROOT / "scripts" / "voice"


def _resolve_module(module: str, *, search: tuple[Path, ...]) -> Path | None:
    parts = module.split(".")
    for base in search:
        file_candidate = base.joinpath(*parts).with_suffix(".py")
        if file_candidate.is_file():
            return file_candidate.resolve()
        package_candidate = base.joinpath(*parts, "__init__.py")
        if package_candidate.is_file():
            return package_candidate.resolve()
    return None


def _relative_module(path: Path, level: int, module: str | None) -> str | None:
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return None
    package = list(relative.with_suffix("").parts[:-1])
    if path.name == "__init__.py":
        package.append(relative.parent.name)
    if level > len(package) + 1:
        return None
    prefix = package[: len(package) - level + 1]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix)


def _local_imports(path: Path) -> tuple[Path, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ()
    found: set[Path] = set()
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative = _relative_module(path, node.level, node.module)
                if relative:
                    modules.append(relative)
            elif node.module:
                modules.append(node.module)
        for module in modules:
            resolved = _resolve_module(module, search=(ROOT, VOICE_DIR))
            if resolved is not None and ROOT in resolved.parents:
                found.add(resolved)
    return tuple(sorted(found))


def dependency_hashes() -> dict[str, str]:
    roots = set(PACKAGE_DIR.glob("*.py"))
    roots.add(VOICE_DIR / "plo_type.py")  # dynamically loaded by hwang_tier
    pending = [path.resolve() for path in roots]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        pending.extend(imported for imported in _local_imports(path) if imported not in visited)
    hashes = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(visited)
    }
    from phevaluator import _pheval

    native_path = Path(_pheval.__file__).resolve()
    hashes[f"dependency:phevaluator-native:{native_path.name}"] = hashlib.sha256(
        native_path.read_bytes()
    ).hexdigest()
    return dict(sorted(hashes.items()))


def own_source_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def provenance_snapshot() -> dict[str, Any]:
    hashes = dependency_hashes()
    versions = {
        "phevaluator": metadata.version("phevaluator"),
        "pokerkit": metadata.version("pokerkit"),
        "python_semantics": f"{sys.version_info.major}.{sys.version_info.minor}",
    }
    material = json.dumps(
        {"hashes": hashes, "versions": versions},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "own_source_hash": own_source_hash(),
        "transitive_hash": hashlib.sha256(material).hexdigest(),
        "dependency_hashes": hashes,
        "dependency_versions": versions,
    }
