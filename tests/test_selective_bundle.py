from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dev_workflow.bundle import resolve_skills


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "harnesses" / "codex"


class SelectiveBundleTests(unittest.TestCase):
    def test_selecting_wrapper_includes_model_invoked_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "selection"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/select_codex_skills.py",
                    "--skill",
                    "grill-me",
                    "--target",
                    str(target),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                result.stdout.strip(), "materialized: grilling, grill-me"
            )
            self.assertTrue((target / "grill-me/SKILL.md").is_file())
            self.assertTrue((target / "grilling/SKILL.md").is_file())
            notice = (target / "dev-workflow-UPSTREAM_LICENSE").read_text()
            self.assertIn("Copyright (c) 2026 Matt Pocock", notice)
            selection = json.loads(
                (target / "dev-workflow-bundle.json").read_text()
            )
            self.assertEqual(
                tuple(selection["skills"]), ("grill-me", "grilling")
            )
            self.assertEqual(selection["skills"]["grill-me"]["requires"], ["grilling"])
            self.assertEqual(selection["skills"]["grill-me"]["path"], "grill-me")
            self.assertEqual(selection["skills"]["grilling"]["path"], "grilling")
            self.assertEqual(
                selection["upstream"]["commit"],
                "6654f6b60cd9d5be8b54c6fafe44346dabeb3b76",
            )

    def test_selecting_primitive_does_not_invent_reverse_dependency(self) -> None:
        manifest = json.loads((BUNDLE / "bundle.json").read_text())
        self.assertEqual(resolve_skills(manifest, ["grilling"]), ("grilling",))

    def test_selector_refuses_a_nonempty_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target / "existing.txt").write_text("preserve me")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/select_codex_skills.py",
                    "--skill",
                    "grill-me",
                    "--target",
                    str(target),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("selection target must be empty", result.stderr)
            self.assertEqual((target / "existing.txt").read_text(), "preserve me")


if __name__ == "__main__":
    unittest.main()
