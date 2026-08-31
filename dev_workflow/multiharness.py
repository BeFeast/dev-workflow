"""Deterministic registry and portable builder for every supported harness."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping

from .generated_claude import (
    UPSTREAM_COMMIT as CLAUDE_UPSTREAM_COMMIT,
    UPSTREAM_LICENSE as CLAUDE_UPSTREAM_LICENSE,
    generated_files as generated_claude_files,
)
from .generated_codex import (
    UPSTREAM_COMMIT as CODEX_UPSTREAM_COMMIT,
    UPSTREAM_LICENSE as CODEX_UPSTREAM_LICENSE,
    generated_files as generated_codex_files,
)
from .generated_opencode import (
    UPSTREAM_COMMIT as OPENCODE_UPSTREAM_COMMIT,
    UPSTREAM_LICENSE as OPENCODE_UPSTREAM_LICENSE,
    generated_files as generated_opencode_files,
)


PORTABLE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HarnessSpec:
    name: str
    manifest_harness: str
    install_subdir: str
    source_module: str
    generated_files: Callable[[], dict[str, str]]


HARNESS_REGISTRY: Mapping[str, HarnessSpec] = {
    "codex": HarnessSpec(
        name="codex",
        manifest_harness="codex",
        install_subdir=".codex/skills",
        source_module="dev_workflow.generated_codex",
        generated_files=generated_codex_files,
    ),
    "claude": HarnessSpec(
        name="claude",
        manifest_harness="claude-code",
        install_subdir=".claude/skills",
        source_module="dev_workflow.generated_claude",
        generated_files=generated_claude_files,
    ),
    "opencode": HarnessSpec(
        name="opencode",
        manifest_harness="opencode",
        install_subdir=".opencode/skills",
        source_module="dev_workflow.generated_opencode",
        generated_files=generated_opencode_files,
    ),
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _upstream_metadata() -> dict[str, str]:
    commits = {
        CODEX_UPSTREAM_COMMIT,
        CLAUDE_UPSTREAM_COMMIT,
        OPENCODE_UPSTREAM_COMMIT,
    }
    notices = {
        CODEX_UPSTREAM_LICENSE,
        CLAUDE_UPSTREAM_LICENSE,
        OPENCODE_UPSTREAM_LICENSE,
    }
    if len(commits) != 1 or len(notices) != 1:
        raise ValueError("harness generators disagree on pinned upstream attribution")
    return {
        "repository": "mattpocock/skills",
        "commit": commits.pop(),
        "license": "MIT",
        "copyright": "Copyright (c) 2026 Matt Pocock",
    }


def _validate_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe portable path: {value!r}")
    return path


def _source_payloads() -> tuple[dict[str, bytes], dict[str, dict[str, object]]]:
    upstream = _upstream_metadata()
    payloads: dict[str, bytes] = {
        "UPSTREAM_LICENSE": CODEX_UPSTREAM_LICENSE.encode("utf-8")
    }
    harnesses: dict[str, dict[str, object]] = {}
    for name, spec in HARNESS_REGISTRY.items():
        generated = spec.generated_files()
        if "bundle.json" not in generated or "UPSTREAM_LICENSE" not in generated:
            raise ValueError(f"{name} generator omits bundle metadata or attribution")
        manifest = json.loads(generated["bundle.json"])
        if manifest.get("harness") != spec.manifest_harness:
            raise ValueError(f"{name} generated manifest names the wrong harness")
        if manifest.get("upstream") != upstream:
            raise ValueError(f"{name} generated manifest has divergent attribution")
        skills = manifest.get("skills")
        if not isinstance(skills, dict) or set(skills) != {"grill-me", "grilling"}:
            raise ValueError(f"{name} generated manifest must contain the linked pair")
        if skills["grill-me"].get("requires") != ["grilling"]:
            raise ValueError(f"{name} wrapper must require grilling")
        if skills["grilling"].get("requires") != []:
            raise ValueError(f"{name} primitive must have no reverse dependency")
        if skills["grilling"].get("invocation") != "model":
            raise ValueError(f"{name} grilling primitive must remain model-invoked")
        if generated["UPSTREAM_LICENSE"] != CODEX_UPSTREAM_LICENSE:
            raise ValueError(f"{name} generated notice differs from the pinned MIT text")

        for relative, text in sorted(generated.items()):
            _validate_relative_path(relative)
            portable = f"harnesses/{name}/{relative}"
            if portable in payloads:
                raise ValueError(f"duplicate portable path: {portable}")
            payloads[portable] = text.encode("utf-8")
        harnesses[name] = {
            "install_subdir": spec.install_subdir,
            "manifest": f"harnesses/{name}/bundle.json",
            "skills": ["grill-me", "grilling"],
            "source_module": spec.source_module,
        }
    return payloads, harnesses


def portable_manifest(payloads: Mapping[str, bytes]) -> dict[str, object]:
    _, harnesses = _source_payloads()
    return {
        "artifact": "dev-workflow-multiharness",
        "schema_version": PORTABLE_SCHEMA_VERSION,
        "source": {
            "generator": "scripts/build_multiharness_bundle.py",
            "repository": "BeFeast/dev-workflow",
        },
        "upstream": _upstream_metadata(),
        "harnesses": harnesses,
        "files": {
            relative: {
                "sha256": sha256_bytes(content),
                "size": len(content),
            }
            for relative, content in sorted(payloads.items())
        },
    }


def build_portable_bundle(output: Path) -> dict[str, object]:
    """Write one timestamp-free portable tree into a new or empty directory."""

    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError(f"portable output must be empty: {output}")
    payloads, _ = _source_payloads()
    for relative, content in sorted(payloads.items()):
        target = output / _validate_relative_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    manifest = portable_manifest(payloads)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_portable_bundle(root: Path) -> dict[str, object]:
    """Verify every portable payload byte against the top-level manifest."""

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact") != "dev-workflow-multiharness":
        raise ValueError("not a dev-workflow multi-harness artifact")
    if manifest.get("schema_version") != PORTABLE_SCHEMA_VERSION:
        raise ValueError("unsupported portable manifest schema")
    if manifest.get("upstream") != _upstream_metadata():
        raise ValueError("portable manifest attribution differs from the pinned source")
    expected_payloads, _ = _source_payloads()
    expected_manifest = portable_manifest(expected_payloads)
    if manifest != expected_manifest:
        raise ValueError("portable manifest differs from the deterministic source")
    records = manifest.get("files")
    if not isinstance(records, dict):
        raise ValueError("portable manifest must contain file checksums")

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if actual != set(records):
        raise ValueError("portable payload files do not match the manifest")
    for relative, record in records.items():
        path = root / _validate_relative_path(relative)
        if not isinstance(record, dict):
            raise ValueError(f"invalid portable checksum record: {relative}")
        content = path.read_bytes()
        if record.get("size") != len(content):
            raise ValueError(f"portable size mismatch: {relative}")
        if record.get("sha256") != sha256_bytes(content):
            raise ValueError(f"portable checksum mismatch: {relative}")
    return manifest


def portable_file_bytes(root: Path) -> dict[str, bytes]:
    """Return all portable files for byte-for-byte determinism assertions."""

    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
