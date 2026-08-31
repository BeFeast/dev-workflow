from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dev_workflow.bundle import install_selection, uninstall_selection
from dev_workflow.multiharness import (
    HARNESS_REGISTRY,
    build_portable_bundle,
    portable_file_bytes,
    verify_portable_bundle,
)


ROOT = Path(__file__).resolve().parents[1]


class MultiHarnessBundleTests(unittest.TestCase):
    def test_portable_build_is_byte_deterministic_and_matches_committed_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            first_manifest = build_portable_bundle(first)
            second_manifest = build_portable_bundle(second)
            self.assertEqual(portable_file_bytes(first), portable_file_bytes(second))
            self.assertEqual(first_manifest, second_manifest)
            self.assertEqual(verify_portable_bundle(first), first_manifest)
            self.assertEqual(
                set(first_manifest["harnesses"]), set(HARNESS_REGISTRY)
            )
            for harness in HARNESS_REGISTRY:
                committed = ROOT / "harnesses" / harness
                portable = first / "harnesses" / harness
                for source in committed.rglob("*"):
                    if source.is_file():
                        relative = source.relative_to(committed)
                        self.assertEqual(
                            source.read_bytes(), (portable / relative).read_bytes()
                        )
            notice = (first / "UPSTREAM_LICENSE").read_text(encoding="utf-8")
            self.assertIn("Copyright (c) 2026 Matt Pocock", notice)

    def test_portable_verification_rejects_tampered_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "artifact"
            build_portable_bundle(artifact)
            target = artifact / "harnesses/codex/skills/grilling/SKILL.md"
            target.write_text(target.read_text(encoding="utf-8") + "tampered\n")
            with self.assertRaisesRegex(ValueError, "size mismatch|checksum mismatch"):
                verify_portable_bundle(artifact)

    def test_portable_verification_rejects_payload_and_directory_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kind in ("payload", "directory"):
                with self.subTest(kind=kind):
                    artifact = root / kind / "artifact"
                    build_portable_bundle(artifact)
                    if kind == "payload":
                        target = artifact / "harnesses/codex/skills/grilling/SKILL.md"
                        external = root / kind / "external.md"
                        external.write_bytes(target.read_bytes())
                        target.unlink()
                        target.symlink_to(external)
                    else:
                        external = root / kind / "external"
                        external.mkdir()
                        (artifact / "extra-directory-link").symlink_to(
                            external, target_is_directory=True
                        )
                    with self.assertRaisesRegex(ValueError, "symlink"):
                        verify_portable_bundle(artifact)

    def test_install_and_uninstall_preserve_unrelated_skills_for_every_harness(self) -> None:
        caller_names = {
            "grill-with-docs",
            "triage",
            "wayfinder",
            "improve-codebase-architecture",
            "domain-modeling",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            build_portable_bundle(artifact)
            for harness, spec in HARNESS_REGISTRY.items():
                isolated = root / f"root-{harness}"
                unrelated = isolated / spec.install_subdir / "unrelated/SKILL.md"
                unrelated.parent.mkdir(parents=True)
                unrelated.write_text("preserve me\n", encoding="utf-8")
                resolved = install_selection(
                    artifact, isolated, harness, ["grill-me"]
                )
                self.assertEqual(resolved, ("grilling", "grill-me"))
                skill_root = isolated / spec.install_subdir
                self.assertTrue((skill_root / "grill-me/SKILL.md").is_file())
                self.assertTrue((skill_root / "grilling/SKILL.md").is_file())
                self.assertTrue(unrelated.is_file())
                installed_names = {path.name for path in skill_root.iterdir()}
                self.assertTrue(caller_names.isdisjoint(installed_names))
                metadata = isolated / ".dev-workflow" / harness
                selection = json.loads(
                    (metadata / "selection.json").read_text(encoding="utf-8")
                )
                self.assertEqual(selection["selected"], ["grill-me"])
                self.assertEqual(selection["resolved"], ["grilling", "grill-me"])
                self.assertIn(
                    "Copyright (c) 2026 Matt Pocock",
                    (metadata / "UPSTREAM_LICENSE").read_text(encoding="utf-8"),
                )

                removed = uninstall_selection(isolated, harness)
                self.assertEqual(removed, resolved)
                self.assertFalse((skill_root / "grill-me").exists())
                self.assertFalse((skill_root / "grilling").exists())
                self.assertEqual(unrelated.read_text(encoding="utf-8"), "preserve me\n")
                self.assertFalse(metadata.exists())

    def test_uninstall_preserves_preexisting_empty_harness_ancestors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            build_portable_bundle(artifact)
            for harness, spec in HARNESS_REGISTRY.items():
                with self.subTest(harness=harness):
                    isolated = root / f"root-{harness}"
                    harness_ancestor = isolated / Path(spec.install_subdir).parts[0]
                    harness_ancestor.mkdir(parents=True)
                    install_selection(artifact, isolated, harness, ["grill-me"])
                    receipt = json.loads(
                        (
                            isolated
                            / ".dev-workflow"
                            / harness
                            / "install-receipt.json"
                        ).read_text(encoding="utf-8")
                    )
                    self.assertNotIn(
                        Path(spec.install_subdir).parts[0], receipt["directories"]
                    )
                    uninstall_selection(isolated, harness)
                    self.assertTrue(harness_ancestor.is_dir())
                    self.assertEqual(list(harness_ancestor.iterdir()), [])

    def test_selecting_primitive_pulls_no_wrapper_or_unrelated_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            isolated = root / "isolated"
            build_portable_bundle(artifact)
            resolved = install_selection(artifact, isolated, "codex", ["grilling"])
            self.assertEqual(resolved, ("grilling",))
            skill_root = isolated / HARNESS_REGISTRY["codex"].install_subdir
            self.assertTrue((skill_root / "grilling/SKILL.md").is_file())
            self.assertFalse((skill_root / "grill-me").exists())
            self.assertEqual(
                {path.name for path in skill_root.iterdir()}, {"grilling"}
            )

    def test_modified_owned_file_blocks_uninstall_without_partial_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            isolated = root / "isolated"
            build_portable_bundle(artifact)
            install_selection(artifact, isolated, "claude", ["grill-me"])
            skill_root = isolated / HARNESS_REGISTRY["claude"].install_subdir
            modified = skill_root / "grilling/SKILL.md"
            modified.write_text("user modified\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "was modified"):
                uninstall_selection(isolated, "claude")
            self.assertEqual(modified.read_text(encoding="utf-8"), "user modified\n")
            self.assertTrue((skill_root / "grill-me/SKILL.md").is_file())
            self.assertTrue(
                (isolated / ".dev-workflow/claude/install-receipt.json").is_file()
            )

    def test_receipt_cannot_claim_an_unrelated_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            isolated = root / "isolated"
            unrelated = isolated / "keep.txt"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("keep me\n", encoding="utf-8")
            build_portable_bundle(artifact)
            install_selection(artifact, isolated, "codex", ["grill-me"])
            receipt_path = isolated / ".dev-workflow/codex/install-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["files"][0] = {
                "path": "keep.txt",
                "sha256": hashlib.sha256(unrelated.read_bytes()).hexdigest(),
                "size": unrelated.stat().st_size,
            }
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "inventory"):
                uninstall_selection(isolated, "codex")
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep me\n")
            self.assertTrue(
                (
                    isolated
                    / HARNESS_REGISTRY["codex"].install_subdir
                    / "grill-me/SKILL.md"
                ).is_file()
            )

    def test_forged_resolved_skill_cannot_delete_an_unrelated_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            isolated = root / "isolated"
            build_portable_bundle(artifact)
            install_selection(artifact, isolated, "codex", ["grill-me"])
            skill_root = isolated / HARNESS_REGISTRY["codex"].install_subdir
            unrelated = skill_root / "unrelated/SKILL.md"
            unrelated.parent.mkdir()
            unrelated.write_text("keep me\n", encoding="utf-8")
            receipt_path = isolated / ".dev-workflow/codex/install-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["resolved"].append("unrelated")
            receipt["files"].append(
                {
                    "path": ".codex/skills/unrelated/SKILL.md",
                    "sha256": hashlib.sha256(unrelated.read_bytes()).hexdigest(),
                    "size": unrelated.stat().st_size,
                }
            )
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "closure"):
                uninstall_selection(isolated, "codex")
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep me\n")
            self.assertTrue((skill_root / "grill-me/SKILL.md").is_file())

    def test_incomplete_receipt_cannot_orphan_an_owned_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            isolated = root / "isolated"
            build_portable_bundle(artifact)
            install_selection(artifact, isolated, "claude", ["grill-me"])
            receipt_path = isolated / ".dev-workflow/claude/install-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            dropped = receipt["files"].pop()
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "complete"):
                uninstall_selection(isolated, "claude")
            dropped_path = isolated / dropped["path"]
            self.assertTrue(dropped_path.is_file())
            self.assertTrue(
                (
                    isolated
                    / HARNESS_REGISTRY["claude"].install_subdir
                    / "grill-me/SKILL.md"
                ).is_file()
            )
            self.assertTrue(receipt_path.is_file())

    def test_existing_selected_skill_collision_fails_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            isolated = root / "isolated"
            build_portable_bundle(artifact)
            existing = (
                isolated
                / HARNESS_REGISTRY["opencode"].install_subdir
                / "grilling/SKILL.md"
            )
            existing.parent.mkdir(parents=True)
            existing.write_text("existing\n", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                install_selection(artifact, isolated, "opencode", ["grill-me"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing\n")
            self.assertFalse((isolated / ".dev-workflow/opencode").exists())

    def test_interrupted_write_rolls_back_file_and_created_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            isolated = root / "isolated"
            build_portable_bundle(artifact)
            interrupted = isolated / ".codex/skills/grilling/SKILL.md"
            original_open = Path.open

            class InterruptedWriter:
                def __init__(self, handle):
                    self.handle = handle

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_value, traceback):
                    self.handle.close()

                def write(self, content):
                    self.handle.write(content[:1])
                    raise KeyboardInterrupt

            def interrupt_one_write(path, mode="r", *args, **kwargs):
                handle = original_open(path, mode, *args, **kwargs)
                if path == interrupted and mode == "xb":
                    return InterruptedWriter(handle)
                return handle

            with patch.object(Path, "open", new=interrupt_one_write):
                with self.assertRaises(KeyboardInterrupt):
                    install_selection(artifact, isolated, "codex", ["grilling"])

            self.assertFalse(interrupted.exists())
            self.assertFalse((isolated / ".codex").exists())
            self.assertFalse((isolated / ".dev-workflow").exists())
            self.assertEqual(
                install_selection(artifact, isolated, "codex", ["grilling"]),
                ("grilling",),
            )

    def test_general_cli_requires_harness_and_round_trips_fixture_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            isolated = root / "isolated"
            build_portable_bundle(artifact)
            install = subprocess.run(
                [
                    sys.executable,
                    "scripts/select_skills.py",
                    "install",
                    "--harness",
                    "opencode",
                    "--root",
                    str(isolated),
                    "--bundle-root",
                    str(artifact),
                    "--skill",
                    "grill-me",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            self.assertEqual(install.stdout.strip(), "installed: grilling, grill-me")
            uninstall = subprocess.run(
                [
                    sys.executable,
                    "scripts/select_skills.py",
                    "uninstall",
                    "--harness",
                    "opencode",
                    "--root",
                    str(isolated),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                uninstall.returncode, 0, uninstall.stdout + uninstall.stderr
            )
            self.assertEqual(
                uninstall.stdout.strip(), "uninstalled: grilling, grill-me"
            )


if __name__ == "__main__":
    unittest.main()
