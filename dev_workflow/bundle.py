"""Selective bundle materialization used by isolated fixture tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def resolve_skills(manifest: dict, selected: list[str]) -> tuple[str, ...]:
    skills = manifest.get("skills")
    if not isinstance(skills, dict):
        raise ValueError("bundle manifest must define skills")
    resolved: list[str] = []
    visiting: set[str] = set()

    def add(name: str) -> None:
        if name in resolved:
            return
        if name in visiting:
            raise ValueError("skill dependency cycle")
        if name not in skills:
            raise ValueError(f"unknown skill {name!r}")
        visiting.add(name)
        dependencies = skills[name].get("requires")
        if not isinstance(dependencies, list) or not all(
            isinstance(item, str) for item in dependencies
        ):
            raise ValueError(f"skill {name!r} has invalid requires")
        for dependency in dependencies:
            add(dependency)
        visiting.remove(name)
        resolved.append(name)

    for skill in selected:
        add(skill)
    return tuple(resolved)


def materialize_fixture(bundle_root: Path, target_root: Path, selected: list[str]) -> tuple[str, ...]:
    """Copy a selection and its linked dependencies into an isolated target."""

    manifest = json.loads((bundle_root / "bundle.json").read_text(encoding="utf-8"))
    resolved = resolve_skills(manifest, selected)
    target_root.mkdir(parents=True, exist_ok=True)
    for name in resolved:
        relative = manifest["skills"][name]["path"]
        source = bundle_root / relative
        target = target_root / name
        if target.exists():
            raise FileExistsError(f"fixture target already exists: {target}")
        shutil.copytree(source, target)
    return resolved
