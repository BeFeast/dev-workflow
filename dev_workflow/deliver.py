"""Approval-gated multi-root delivery with fail-closed targets and rollback.

Delivery orchestrates the tested :func:`install_selection` /
:func:`uninstall_selection` receipt primitives across the three harness roots
pinned by a ``dev-workflow/install-targets-v1`` document.  It records the
before-state, installs atomically (any failure rolls back the roots already
touched), and rolls back by removing only the links this delivery created.

No target path or secret is embedded here: the caller supplies the resolved
targets document, which the approved runtime environment materializes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional, Sequence

from .bundle import install_selection, uninstall_selection
from .multiharness import HARNESS_REGISTRY

TARGETS_SCHEMA = "dev-workflow/install-targets-v1"
DELIVERY_STATE_NAME = "delivery-state.json"
DELIVERY_STATE_VERSION = 1


def resolve_targets(document: Mapping[str, object]) -> dict[str, Path]:
    """Validate an install-targets document and return one root per harness."""

    if not isinstance(document, Mapping) or document.get("schema") != TARGETS_SCHEMA:
        raise ValueError("install targets must declare the install-targets-v1 schema")
    targets = document.get("targets")
    if not isinstance(targets, Mapping):
        raise ValueError("install targets must map every harness to a root")
    if set(targets) != set(HARNESS_REGISTRY):
        raise ValueError("install targets must pin exactly the supported harness roots")
    resolved: dict[str, Path] = {}
    for harness in HARNESS_REGISTRY:
        value = targets[harness]
        if not isinstance(value, str) or not value:
            raise ValueError(f"install target for {harness!r} must be a non-empty path")
        resolved[harness] = Path(value)
    return resolved


def _require_present_root(harness: str, root: Path) -> None:
    """Fail closed before any mutation when a pinned target is missing."""

    if root.is_symlink() or not root.is_dir():
        raise FileNotFoundError(f"install target for {harness!r} is missing: {root}")


def _install_subdir_snapshot(harness: str, root: Path) -> list[str]:
    """Record the pre-existing skill directory names under the harness root."""

    skills_root = root / HARNESS_REGISTRY[harness].install_subdir
    if skills_root.is_symlink() or not skills_root.is_dir():
        return []
    return sorted(path.name for path in skills_root.iterdir())


def deliver_selection(
    bundle_root: Path,
    targets_document: Mapping[str, object],
    selected: Sequence[str],
    state_dir: Path,
    release: Optional[Mapping[str, object]] = None,
) -> dict[str, object]:
    """Install the selection into every pinned root, recording the before-state.

    Every target root must already exist; a missing root fails closed before a
    byte is written.  If any root's install fails, the roots already installed
    are rolled back so the delivery is all-or-nothing.
    """

    selected = list(selected)
    resolved = resolve_targets(targets_document)
    for harness in HARNESS_REGISTRY:
        _require_present_root(harness, resolved[harness])

    state_path = state_dir / DELIVERY_STATE_NAME
    if state_path.exists() or state_path.is_symlink():
        raise FileExistsError(f"delivery state already exists: {state_path}")

    before = {
        harness: _install_subdir_snapshot(harness, resolved[harness])
        for harness in HARNESS_REGISTRY
    }
    installed: list[str] = []
    delivered: dict[str, list[str]] = {}
    try:
        for harness in HARNESS_REGISTRY:
            skills = install_selection(
                bundle_root, resolved[harness], harness, selected
            )
            installed.append(harness)
            delivered[harness] = list(skills)
    except BaseException:
        for harness in reversed(installed):
            uninstall_selection(resolved[harness], harness)
        raise

    journal: dict[str, object] = {
        "schema_version": DELIVERY_STATE_VERSION,
        "selected": selected,
        "targets": {harness: str(resolved[harness]) for harness in HARNESS_REGISTRY},
        "before": before,
        "delivered": delivered,
    }
    if release is not None:
        journal["release"] = dict(release)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(journal, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return journal


def rollback_selection(state_dir: Path) -> dict[str, object]:
    """Remove only this delivery's links and confirm the before-state returns."""

    state_path = state_dir / DELIVERY_STATE_NAME
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError("delivery state must be a regular non-symlink file")
    journal = json.loads(state_path.read_text(encoding="utf-8"))
    if journal.get("schema_version") != DELIVERY_STATE_VERSION:
        raise ValueError("unsupported delivery state schema")
    targets = journal.get("targets")
    before = journal.get("before")
    if not isinstance(targets, Mapping) or set(targets) != set(HARNESS_REGISTRY):
        raise ValueError("delivery state does not pin every harness target")
    if not isinstance(before, Mapping) or set(before) != set(HARNESS_REGISTRY):
        raise ValueError("delivery state is missing a before-state snapshot")

    resolved = {harness: Path(str(targets[harness])) for harness in HARNESS_REGISTRY}
    removed: dict[str, list[str]] = {}
    for harness in HARNESS_REGISTRY:
        removed[harness] = list(uninstall_selection(resolved[harness], harness))

    for harness in HARNESS_REGISTRY:
        current = _install_subdir_snapshot(harness, resolved[harness])
        if current != list(before[harness]):
            raise ValueError(f"rollback did not restore the prior state for {harness!r}")

    state_path.unlink()
    return {"removed": removed, "reconciled": True}
