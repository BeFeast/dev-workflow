"""Dependency-aware selection plus receipt-owned isolated installation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .multiharness import HARNESS_REGISTRY, sha256_bytes, verify_portable_bundle


RECEIPT_NAMESPACE = ".dev-workflow"
RECEIPT_NAME = "install-receipt.json"


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


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe bundle path: {value!r}")
    return path


def _harness_bundle_root(source_root: Path, harness: str) -> Path:
    if harness not in HARNESS_REGISTRY:
        raise ValueError(f"unknown harness {harness!r}")
    if (source_root / "manifest.json").is_file():
        verify_portable_bundle(source_root)
        candidate = source_root / "harnesses" / harness
    elif (source_root / harness / "bundle.json").is_file():
        candidate = source_root / harness
    elif source_root.name == harness and (source_root / "bundle.json").is_file():
        candidate = source_root
    else:
        raise ValueError(f"cannot find {harness!r} bundle under {source_root}")
    if not (candidate / "bundle.json").is_file():
        raise ValueError(f"{harness!r} bundle metadata is missing")
    return candidate


def _target_path(root: Path, relative: Path) -> Path:
    target = root / relative
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise ValueError(f"target path escapes the isolated root: {relative}")
    return target


def _remove_empty_parents(path: Path, root: Path) -> None:
    root = root.resolve()
    current = path
    while current.exists() and current.resolve() != root:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def install_selection(
    source_root: Path,
    target_root: Path,
    harness: str,
    selected: list[str],
) -> tuple[str, ...]:
    """Install selected linked skills into an isolated harness root.

    Existing unrelated skills are preserved.  Any selected-skill collision or
    existing receipt fails closed before a byte is written.
    """

    spec = HARNESS_REGISTRY.get(harness)
    if spec is None:
        raise ValueError(f"unknown harness {harness!r}")
    if not selected:
        raise ValueError("at least one skill must be selected")
    bundle_root = _harness_bundle_root(source_root, harness)
    manifest = json.loads((bundle_root / "bundle.json").read_text(encoding="utf-8"))
    if manifest.get("harness") != spec.manifest_harness:
        raise ValueError(f"bundle manifest does not describe {harness!r}")
    resolved = resolve_skills(manifest, selected)

    target_root.mkdir(parents=True, exist_ok=True)
    receipt_relative = Path(RECEIPT_NAMESPACE) / harness / RECEIPT_NAME
    receipt_path = _target_path(target_root, receipt_relative)
    metadata_root = receipt_path.parent
    if metadata_root.exists() or metadata_root.is_symlink():
        raise FileExistsError(f"install metadata already exists: {metadata_root}")

    install_root = _safe_relative(spec.install_subdir)
    planned: list[tuple[Path, bytes]] = []
    for name in resolved:
        skill = manifest["skills"][name]
        source = bundle_root / _safe_relative(skill["path"])
        destination_root = install_root / name
        destination = _target_path(target_root, destination_root)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(
                f"selected skill already exists: {destination_root.as_posix()}"
            )
        if not source.is_dir() or source.is_symlink():
            raise ValueError(f"bundle skill path is not a directory: {source}")
        files = [path for path in sorted(source.rglob("*")) if path.is_file()]
        if not files or any(path.is_symlink() for path in files):
            raise ValueError(f"bundle skill has no regular portable files: {name}")
        for path in files:
            relative = destination_root / path.relative_to(source)
            planned.append((relative, path.read_bytes()))

    selection = {
        **{key: value for key, value in manifest.items() if key != "skills"},
        "selected": selected,
        "resolved": list(resolved),
        "skills": {
            name: {**manifest["skills"][name], "path": name}
            for name in resolved
        },
    }
    metadata_relative = Path(RECEIPT_NAMESPACE) / harness
    planned.extend(
        (
            (
                metadata_relative / "selection.json",
                (json.dumps(selection, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            ),
            (
                metadata_relative / "UPSTREAM_LICENSE",
                (bundle_root / "UPSTREAM_LICENSE").read_bytes(),
            ),
        )
    )
    planned.sort(key=lambda item: item[0].as_posix())
    for relative, _ in planned:
        target = _target_path(target_root, relative)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"install destination already exists: {relative}")

    receipt = {
        "schema_version": 1,
        "harness": harness,
        "install_subdir": spec.install_subdir,
        "selected": selected,
        "resolved": list(resolved),
        "files": [
            {
                "path": relative.as_posix(),
                "sha256": sha256_bytes(content),
                "size": len(content),
            }
            for relative, content in planned
        ],
    }
    created: list[Path] = []
    try:
        for relative, content in planned:
            target = _target_path(target_root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(content)
            created.append(target)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with receipt_path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        created.append(receipt_path)
    except Exception:
        for target in reversed(created):
            if target.is_file() or target.is_symlink():
                target.unlink()
            _remove_empty_parents(target.parent, target_root)
        raise
    return resolved


def uninstall_selection(target_root: Path, harness: str) -> tuple[str, ...]:
    """Remove only checksum-matching files owned by one install receipt."""

    if harness not in HARNESS_REGISTRY:
        raise ValueError(f"unknown harness {harness!r}")
    receipt_relative = Path(RECEIPT_NAMESPACE) / harness / RECEIPT_NAME
    receipt_path = _target_path(target_root, receipt_relative)
    if receipt_path.is_symlink():
        raise ValueError("install receipt must not be a symlink")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema_version") != 1 or receipt.get("harness") != harness:
        raise ValueError("install receipt does not match the requested harness")
    spec = HARNESS_REGISTRY[harness]
    if receipt.get("install_subdir") != spec.install_subdir:
        raise ValueError("install receipt names the wrong harness skill root")
    records = receipt.get("files")
    if not isinstance(records, list) or not records:
        raise ValueError("install receipt has no owned files")

    resolved = receipt.get("resolved")
    if (
        not isinstance(resolved, list)
        or not resolved
        or not all(
            isinstance(item, str)
            and item
            and "/" not in item
            and "\\" not in item
            for item in resolved
        )
    ):
        raise ValueError("install receipt has invalid resolved skills")
    allowed_skill_roots = [
        _safe_relative(spec.install_subdir) / name for name in resolved
    ]
    allowed_metadata = {
        Path(RECEIPT_NAMESPACE) / harness / "selection.json",
        Path(RECEIPT_NAMESPACE) / harness / "UPSTREAM_LICENSE",
    }

    owned: list[Path] = []
    seen: set[Path] = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("install receipt contains an invalid file record")
        relative = _safe_relative(record["path"])
        if relative in seen:
            raise ValueError(f"install receipt repeats an owned file: {relative}")
        seen.add(relative)
        if relative not in allowed_metadata and not any(
            relative != prefix and prefix in relative.parents
            for prefix in allowed_skill_roots
        ):
            raise ValueError(f"install receipt claims an unrelated path: {relative}")
        path = _target_path(target_root, relative)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"owned install file is missing or unsafe: {relative}")
        content = path.read_bytes()
        if record.get("size") != len(content) or record.get("sha256") != sha256_bytes(
            content
        ):
            raise ValueError(f"owned install file was modified: {relative}")
        owned.append(path)

    for path in reversed(owned):
        path.unlink()
        _remove_empty_parents(path.parent, target_root)
    receipt_path.unlink()
    _remove_empty_parents(receipt_path.parent, target_root)
    return tuple(resolved)
