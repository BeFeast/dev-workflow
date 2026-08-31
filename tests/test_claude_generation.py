from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from dev_workflow.generated_claude import UPSTREAM_COMMIT, generated_files


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "harnesses" / "claude"
GENERATOR = ROOT / "scripts" / "generate_claude_skills.py"
VALIDATOR = ROOT / "scripts" / "validate_claude_skills.py"


class ClaudeGenerationTests(unittest.TestCase):
    def test_committed_bundle_is_current(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(GENERATOR), "--check"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_generation_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for output in (first, second):
                subprocess.run(
                    [sys.executable, str(GENERATOR), "--output", output],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            first_files = {
                path.relative_to(first): path.read_bytes()
                for path in Path(first).rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second): path.read_bytes()
                for path in Path(second).rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_files, second_files)

    def test_linked_skills_ship_together_with_invocation_metadata(self) -> None:
        manifest = json.loads((HARNESS / "bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["harness"], "claude-code")
        self.assertEqual(manifest["skills"]["grill-me"]["invocation"], "user")
        self.assertEqual(manifest["skills"]["grill-me"]["requires"], ["grilling"])
        self.assertEqual(manifest["skills"]["grilling"]["invocation"], "model")
        for skill in manifest["skills"].values():
            self.assertTrue((HARNESS / skill["path"] / "SKILL.md").is_file())

    def test_generated_skills_pass_claude_validator(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(VALIDATOR), str(HARNESS)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_wrapper_calls_primitive_and_only_primitive_owns_interview(self) -> None:
        wrapper = (HARNESS / "skills/grill-me/SKILL.md").read_text(encoding="utf-8")
        primitive = (HARNESS / "skills/grilling/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("disable-model-invocation: true", wrapper)
        self.assertIn("user-invocable: false", primitive)
        self.assertIn("linked `grilling` skill", wrapper)
        self.assertNotIn("AskUserQuestion", wrapper)
        self.assertIn("`AskUserQuestion` in Claude Code", primitive)
        self.assertIn("Map this as a **design tree**", primitive)
        self.assertNotIn("❓ **Q1**", primitive)

    def test_generated_files_retain_upstream_mit_notice(self) -> None:
        manifest = json.loads(generated_files()["bundle.json"])
        self.assertEqual(manifest["upstream"]["commit"], UPSTREAM_COMMIT)
        notice = (HARNESS / "UPSTREAM_LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", notice)
        self.assertIn("Copyright (c) 2026 Matt Pocock", notice)


if __name__ == "__main__":
    unittest.main()
