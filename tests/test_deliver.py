from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from dev_workflow.deliver import (
    DELIVERY_STATE_NAME,
    TARGETS_SCHEMA,
    deliver_selection,
    resolve_targets,
    rollback_selection,
)
from dev_workflow.multiharness import HARNESS_REGISTRY, build_portable_bundle


ROOT = Path(__file__).resolve().parents[1]


def _targets_document(roots: dict[str, Path]) -> dict[str, object]:
    return {
        "schema": TARGETS_SCHEMA,
        "targets": {harness: str(roots[harness]) for harness in HARNESS_REGISTRY},
    }


def _skill_names(root: Path, harness: str) -> list[str]:
    skills_root = root / HARNESS_REGISTRY[harness].install_subdir
    if not skills_root.is_dir():
        return []
    return sorted(path.name for path in skills_root.iterdir())


class DeliverOrchestratorTests(unittest.TestCase):
    def _prepare(self, base: Path) -> tuple[Path, dict[str, Path]]:
        artifact = base / "artifact"
        build_portable_bundle(artifact)
        roots = {}
        for harness in HARNESS_REGISTRY:
            root = base / f"root-{harness}"
            root.mkdir()
            roots[harness] = root
        return artifact, roots

    def test_delivery_installs_every_root_and_records_before_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifact, roots = self._prepare(base)
            spec = HARNESS_REGISTRY["codex"]
            unrelated = roots["codex"] / spec.install_subdir / "unrelated"
            unrelated.mkdir(parents=True)
            (unrelated / "SKILL.md").write_text("keep me\n", encoding="utf-8")
            state = base / "state"
            state.mkdir()

            journal = deliver_selection(
                artifact, _targets_document(roots), ["grill-me"], state
            )

            self.assertEqual(journal["before"]["codex"], ["unrelated"])
            self.assertEqual(journal["before"]["claude"], [])
            for harness in HARNESS_REGISTRY:
                self.assertEqual(
                    journal["delivered"][harness], ["grilling", "grill-me"]
                )
                self.assertIn("grill-me", _skill_names(roots[harness], harness))
                self.assertIn("grilling", _skill_names(roots[harness], harness))
            self.assertTrue((state / DELIVERY_STATE_NAME).is_file())

            report = rollback_selection(state)
            self.assertTrue(report["reconciled"])
            self.assertEqual(_skill_names(roots["codex"], "codex"), ["unrelated"])
            self.assertEqual(_skill_names(roots["claude"], "claude"), [])
            self.assertEqual(
                (unrelated / "SKILL.md").read_text(encoding="utf-8"), "keep me\n"
            )
            self.assertFalse((state / DELIVERY_STATE_NAME).exists())

    def test_missing_target_fails_closed_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifact, roots = self._prepare(base)
            shutil.rmtree(roots["claude"])
            state = base / "state"
            state.mkdir()
            with self.assertRaises(FileNotFoundError):
                deliver_selection(
                    artifact, _targets_document(roots), ["grill-me"], state
                )
            self.assertFalse(
                (roots["codex"] / HARNESS_REGISTRY["codex"].install_subdir).exists()
            )
            self.assertFalse((state / DELIVERY_STATE_NAME).exists())

    def test_partial_failure_rolls_back_completed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifact, roots = self._prepare(base)
            spec = HARNESS_REGISTRY["opencode"]
            collision = roots["opencode"] / spec.install_subdir / "grilling"
            collision.mkdir(parents=True)
            (collision / "SKILL.md").write_text("existing\n", encoding="utf-8")
            state = base / "state"
            state.mkdir()
            with self.assertRaises(FileExistsError):
                deliver_selection(
                    artifact, _targets_document(roots), ["grill-me"], state
                )
            for harness in ("codex", "claude"):
                self.assertEqual(_skill_names(roots[harness], harness), [])
                self.assertFalse((roots[harness] / ".dev-workflow" / harness).exists())
            self.assertEqual(
                (collision / "SKILL.md").read_text(encoding="utf-8"), "existing\n"
            )
            self.assertFalse((state / DELIVERY_STATE_NAME).exists())

    def test_resolve_targets_requires_schema_and_every_harness(self) -> None:
        with self.assertRaises(ValueError):
            resolve_targets({"schema": "other", "targets": {}})
        with self.assertRaises(ValueError):
            resolve_targets({"schema": TARGETS_SCHEMA, "targets": {"codex": "/tmp/x"}})


@unittest.skipUnless(shutil.which("git"), "git is required for the entrypoint test")
class DeliverEntrypointTests(unittest.TestCase):
    """Drive scripts/deliver.sh against a self-contained fixture git repo."""

    def _make_repo(self, base: Path) -> Path:
        repo = base / "repo"
        repo.mkdir()
        for name in ("dev_workflow", "scripts"):
            shutil.copytree(
                ROOT / name,
                repo / name,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=fixture@example.com",
                "-c",
                "user.name=fixture",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=repo,
            check=True,
            env=env,
        )
        return repo

    def _run(self, repo: Path, args: list[str], env: dict[str, str]):
        full = {**os.environ, "DEV_WORKFLOW_REPO_ROOT": str(repo)}
        full.update(env)
        return subprocess.run(
            [str(repo / "scripts" / "deliver.sh"), *args],
            env=full,
            text=True,
            capture_output=True,
        )

    def _fixture_targets(self, base: Path) -> tuple[dict[str, Path], Path]:
        roots = {}
        for harness in HARNESS_REGISTRY:
            root = base / f"root-{harness}"
            root.mkdir()
            roots[harness] = root
        targets = base / "targets.json"
        targets.write_text(
            json.dumps(_targets_document(roots)) + "\n", encoding="utf-8"
        )
        return roots, targets

    def test_missing_approval_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo = self._make_repo(base)
            roots, targets = self._fixture_targets(base)
            state = base / "state"
            state.mkdir()
            result = self._run(
                repo,
                [],
                {
                    "DEV_WORKFLOW_DELIVERY_STATE_DIR": str(state),
                    "DEV_WORKFLOW_INSTALL_TARGETS": str(targets),
                    "DEV_WORKFLOW_DELIVER_APPROVED": "",
                },
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("not approved", result.stderr)
            self.assertEqual(_skill_names(roots["codex"], "codex"), [])
            self.assertEqual(list(state.iterdir()), [])

    def test_missing_target_fails_closed_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo = self._make_repo(base)
            roots, _ = self._fixture_targets(base)
            unrelated = roots["codex"] / HARNESS_REGISTRY["codex"].install_subdir / "unrelated"
            unrelated.mkdir(parents=True)
            (unrelated / "SKILL.md").write_text("keep me\n", encoding="utf-8")
            bad = base / "bad-targets.json"
            broken = {harness: str(roots[harness]) for harness in HARNESS_REGISTRY}
            broken["claude"] = str(base / "does-not-exist")
            bad.write_text(
                json.dumps({"schema": TARGETS_SCHEMA, "targets": broken}) + "\n",
                encoding="utf-8",
            )
            state = base / "state"
            state.mkdir()
            result = self._run(
                repo,
                [],
                {
                    "DEV_WORKFLOW_DELIVER_APPROVED": "1",
                    "DEV_WORKFLOW_DELIVERY_STATE_DIR": str(state),
                    "DEV_WORKFLOW_INSTALL_TARGETS": str(bad),
                },
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("missing", result.stderr)
            self.assertEqual(_skill_names(roots["codex"], "codex"), ["unrelated"])
            self.assertEqual(list(state.iterdir()), [])

    def test_approved_install_and_rollback_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo = self._make_repo(base)
            roots, targets = self._fixture_targets(base)
            unrelated = roots["codex"] / HARNESS_REGISTRY["codex"].install_subdir / "unrelated"
            unrelated.mkdir(parents=True)
            (unrelated / "SKILL.md").write_text("keep me\n", encoding="utf-8")
            state = base / "state"
            state.mkdir()

            install = self._run(
                repo,
                [],
                {
                    "DEV_WORKFLOW_DELIVER_APPROVED": "1",
                    "DEV_WORKFLOW_DELIVERY_STATE_DIR": str(state),
                    "DEV_WORKFLOW_INSTALL_TARGETS": str(targets),
                },
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            for harness in HARNESS_REGISTRY:
                self.assertIn("grill-me", _skill_names(roots[harness], harness))
                self.assertIn("grilling", _skill_names(roots[harness], harness))
            journal = json.loads((state / DELIVERY_STATE_NAME).read_text(encoding="utf-8"))
            self.assertEqual(journal["release"]["version"], "0.1.0")
            self.assertEqual(len(journal["release"]["bundle"]["checksum"]), 64)

            rollback = self._run(
                repo,
                ["--rollback"],
                {
                    "DEV_WORKFLOW_DELIVER_APPROVED": "1",
                    "DEV_WORKFLOW_DELIVERY_STATE_DIR": str(state),
                },
            )
            self.assertEqual(rollback.returncode, 0, rollback.stdout + rollback.stderr)
            self.assertEqual(_skill_names(roots["codex"], "codex"), ["unrelated"])
            self.assertEqual(_skill_names(roots["opencode"], "opencode"), [])
            self.assertEqual(
                (unrelated / "SKILL.md").read_text(encoding="utf-8"), "keep me\n"
            )
            self.assertFalse((state / DELIVERY_STATE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
