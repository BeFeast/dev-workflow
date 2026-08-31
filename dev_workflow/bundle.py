"""Dependency-aware selective materialization for the Codex bundle."""

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


def materialize_selection(
    bundle_root: Path, target_root: Path, selected: list[str]
) -> tuple[str, ...]:
    """Copy a complete portable selection into an empty isolated target.

    The output is shaped like a Codex skill root, but issue #1 callers use only
    temporary or otherwise isolated targets.  Live installation remains a
    separate approval-gated delivery concern.
    """

    manifest = json.loads((bundle_root / "bundle.json").read_text(encoding="utf-8"))
    resolved = resolve_skills(manifest, selected)
    target_root.mkdir(parents=True, exist_ok=True)
    if any(target_root.iterdir()):
        raise FileExistsError(f"selection target must be empty: {target_root}")

    for name in resolved:
        relative = manifest["skills"][name]["path"]
        source = bundle_root / relative
        target = target_root / name
        shutil.copytree(source, target)

    selected_manifest = {
        **{key: value for key, value in manifest.items() if key != "skills"},
        "selected": selected,
        "skills": {
            name: {**manifest["skills"][name], "path": name}
            for name in resolved
        },
    }
    (target_root / "dev-workflow-bundle.json").write_text(
        json.dumps(selected_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    shutil.copyfile(
        bundle_root / "UPSTREAM_LICENSE",
        target_root / "dev-workflow-UPSTREAM_LICENSE",
    )
    return resolved
