"""Dependency-aware selection plus receipt-owned isolated installation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .multiharness import HARNESS_REGISTRY, sha256_bytes, verify_portable_bundle


RECEIPT_NAMESPACE = ".dev-workflow"
RECEIPT_NAME = "install-receipt.json"
RECEIPT_SCHEMA_VERSION = 2


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


def _canonical_harness_files(harness: str) -> tuple[dict, dict[str, bytes]]:
    spec = HARNESS_REGISTRY[harness]
    generated = spec.generated_files()
    files = {
        _safe_relative(relative).as_posix(): content.encode("utf-8")
        for relative, content in generated.items()
    }
    manifest = json.loads(files["bundle.json"].decode("utf-8"))
    if manifest.get("harness") != spec.manifest_harness:
        raise ValueError(f"canonical bundle does not describe {harness!r}")
    return manifest, files


def _verify_harness_bundle(bundle_root: Path, harness: str) -> tuple[dict, dict[str, bytes]]:
    """Require an exact regular-file copy of the pinned harness generator."""

    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise ValueError(f"{harness!r} bundle root must be a regular directory")
    manifest, expected = _canonical_harness_files(harness)
    actual: dict[str, bytes] = {}
    for path in bundle_root.rglob("*"):
        relative = path.relative_to(bundle_root).as_posix()
        if path.is_symlink():
            raise ValueError(f"bundle contains a symlink: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"bundle contains a special entry: {relative}")
        actual[relative] = path.read_bytes()
    if actual != expected:
        raise ValueError(f"{harness!r} bundle differs from its pinned generator")
    return manifest, actual


def _target_path(root: Path, relative: Path) -> Path:
    target = root / relative
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise ValueError(f"target path escapes the isolated root: {relative}")
    return target


def _create_parent_directories(
    target: Path, root: Path, created: list[Path]
) -> None:
    """Create target parents while recording only directories this call owns."""

    resolved_root = root.resolve()
    missing: list[Path] = []
    current = target.parent
    while current.resolve() != resolved_root:
        if resolved_root not in current.resolve().parents:
            raise ValueError(f"target parent escapes the isolated root: {target}")
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise ValueError(f"target parent is not a safe directory: {current}")
            break
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        try:
            directory.mkdir()
        except FileExistsError:
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError(
                    f"target parent is not a safe directory: {directory}"
                )
        else:
            created.append(directory)


def _selection_plan(
    harness: str,
    manifest: dict,
    bundle_files: dict[str, bytes],
    selected: list[str],
) -> tuple[tuple[str, ...], list[tuple[Path, bytes]]]:
    """Return the canonical dependency closure and complete install inventory."""

    spec = HARNESS_REGISTRY[harness]
    resolved = resolve_skills(manifest, selected)
    install_root = _safe_relative(spec.install_subdir)
    planned: list[tuple[Path, bytes]] = []
    for name in resolved:
        source_root = _safe_relative(manifest["skills"][name]["path"])
        prefix = source_root.as_posix().rstrip("/") + "/"
        skill_files = [
            (relative, content)
            for relative, content in bundle_files.items()
            if relative.startswith(prefix)
        ]
        if not skill_files:
            raise ValueError(f"canonical bundle skill has no files: {name}")
        for relative, content in skill_files:
            source_relative = Path(relative).relative_to(source_root)
            planned.append((install_root / name / source_relative, content))

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
                (json.dumps(selection, indent=2, sort_keys=True) + "\n").encode(
                    "utf-8"
                ),
            ),
            (metadata_relative / "UPSTREAM_LICENSE", bundle_files["UPSTREAM_LICENSE"]),
        )
    )
    planned.sort(key=lambda item: item[0].as_posix())
    return resolved, planned


def _file_records(planned: list[tuple[Path, bytes]]) -> list[dict[str, object]]:
    return [
        {
            "path": relative.as_posix(),
            "sha256": sha256_bytes(content),
            "size": len(content),
        }
        for relative, content in planned
    ]


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
    if (
        not selected
        or not all(isinstance(name, str) and name for name in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("selected skills must be a nonempty unique string list")
    bundle_root = _harness_bundle_root(source_root, harness)
    manifest, bundle_files = _verify_harness_bundle(bundle_root, harness)
    resolved, planned = _selection_plan(
        harness, manifest, bundle_files, selected
    )

    target_root.mkdir(parents=True, exist_ok=True)
    receipt_relative = Path(RECEIPT_NAMESPACE) / harness / RECEIPT_NAME
    receipt_path = _target_path(target_root, receipt_relative)
    metadata_root = receipt_path.parent
    if metadata_root.exists() or metadata_root.is_symlink():
        raise FileExistsError(f"install metadata already exists: {metadata_root}")

    install_root = _safe_relative(spec.install_subdir)
    for name in resolved:
        destination_root = install_root / name
        destination = _target_path(target_root, destination_root)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(
                f"selected skill already exists: {destination_root.as_posix()}"
            )
    for relative, _ in planned:
        target = _target_path(target_root, relative)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"install destination already exists: {relative}")

    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "harness": harness,
        "install_subdir": spec.install_subdir,
        "selected": selected,
        "resolved": list(resolved),
        "files": _file_records(planned),
        "directories": [],
    }
    created: list[Path] = []
    created_directories: list[Path] = []
    try:
        for relative, content in planned:
            target = _target_path(target_root, relative)
            _create_parent_directories(target, target_root, created_directories)
            with target.open("xb") as output:
                output.write(content)
            created.append(target)
        _create_parent_directories(receipt_path, target_root, created_directories)
        receipt["directories"] = sorted(
            directory.relative_to(target_root).as_posix()
            for directory in created_directories
        )
        with receipt_path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        created.append(receipt_path)
    except Exception:
        for target in reversed(created):
            if target.is_file() or target.is_symlink():
                target.unlink()
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
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
    if (
        receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or receipt.get("harness") != harness
    ):
        raise ValueError("install receipt does not match the requested harness")
    spec = HARNESS_REGISTRY[harness]
    if receipt.get("install_subdir") != spec.install_subdir:
        raise ValueError("install receipt names the wrong harness skill root")
    selected = receipt.get("selected")
    resolved = receipt.get("resolved")
    if (
        not isinstance(selected, list)
        or not selected
        or not all(isinstance(item, str) and item for item in selected)
        or len(set(selected)) != len(selected)
        or not isinstance(resolved, list)
        or not resolved
        or not all(isinstance(item, str) and item for item in resolved)
    ):
        raise ValueError("install receipt has invalid selected or resolved skills")

    canonical_manifest, canonical_files = _canonical_harness_files(harness)
    canonical_resolved, canonical_planned = _selection_plan(
        harness, canonical_manifest, canonical_files, selected
    )
    if resolved != list(canonical_resolved):
        raise ValueError("install receipt dependency closure is not canonical")
    expected_records = _file_records(canonical_planned)
    records = receipt.get("files")
    if records != expected_records:
        raise ValueError("install receipt file inventory is not canonical or complete")

    directory_records = receipt.get("directories")
    if (
        not isinstance(directory_records, list)
        or not all(isinstance(item, str) for item in directory_records)
        or len(set(directory_records)) != len(directory_records)
        or directory_records != sorted(directory_records)
    ):
        raise ValueError("install receipt has invalid directory ownership")
    required_metadata_directory = Path(RECEIPT_NAMESPACE) / harness
    if required_metadata_directory.as_posix() not in directory_records:
        raise ValueError("install receipt omits its owned metadata directory")
    receipt_relative = Path(RECEIPT_NAMESPACE) / harness / RECEIPT_NAME
    allowed_directories: set[Path] = set()
    for relative, _ in canonical_planned + [(receipt_relative, b"")]:
        allowed_directories.update(
            parent
            for parent in relative.parents
            if parent != Path(".") and parent.parts
        )
    owned_directories: list[Path] = []
    for value in directory_records:
        relative = _safe_relative(value)
        if relative not in allowed_directories:
            raise ValueError(
                f"install receipt claims an unrelated directory: {relative}"
            )
        directory = _target_path(target_root, relative)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"owned install directory is missing or unsafe: {relative}")
        owned_directories.append(directory)

    owned: list[Path] = []
    for record in expected_records:
        relative = _safe_relative(str(record["path"]))
        path = _target_path(target_root, relative)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"owned install file is missing or unsafe: {relative}")
        content = path.read_bytes()
        if record["size"] != len(content) or record["sha256"] != sha256_bytes(
            content
        ):
            raise ValueError(f"owned install file was modified: {relative}")
        owned.append(path)

    for path in reversed(owned):
        path.unlink()
    receipt_path.unlink()
    for directory in sorted(
        owned_directories, key=lambda path: len(path.parts), reverse=True
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    return canonical_resolved
