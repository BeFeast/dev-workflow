from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dev_workflow.generated_codex import generated_files
from scripts.validate_skills import parse_frontmatter, validate_skill


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "harnesses" / "codex"


class GenerationTests(unittest.TestCase):
    def test_committed_bundle_is_current(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/generate_codex_skills.py", "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generation_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for output in (first, second):
                result = subprocess.run(
                    [
                        sys.executable,
                        "scripts/generate_codex_skills.py",
                        "--output",
                        output,
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for relative in generated_files():
                self.assertEqual(
                    (Path(first) / relative).read_bytes(),
                    (Path(second) / relative).read_bytes(),
                )

    def test_generated_skills_follow_skill_creator_contract(self) -> None:
        for name in ("grill-me", "grilling"):
            path = BUNDLE / "skills" / name
            self.assertEqual(validate_skill(path), [])
            frontmatter = parse_frontmatter((path / "SKILL.md").read_text())
            self.assertEqual(set(frontmatter), {"name", "description"})

    def test_wrapper_and_primitive_remain_linked_and_distinct(self) -> None:
        wrapper = (BUNDLE / "skills/grill-me/SKILL.md").read_text()
        primitive = (BUNDLE / "skills/grilling/SKILL.md").read_text()
        wrapper_metadata = (
            BUNDLE / "skills/grill-me/agents/openai.yaml"
        ).read_text()
        primitive_metadata = (
            BUNDLE / "skills/grilling/agents/openai.yaml"
        ).read_text()
        self.assertIn("$grilling", wrapper)
        self.assertNotIn("request_user_input", wrapper)
        self.assertIn("Use Codex's native `request_user_input`", primitive)
        self.assertIn("Interview the user relentlessly", primitive)
        self.assertIn("Map this as a **design tree**", primitive)
        self.assertNotIn("❓ **Q1**", primitive)
        self.assertIn("allow_implicit_invocation: false", wrapper_metadata)
        self.assertIn("allow_implicit_invocation: true", primitive_metadata)

    def test_generated_bundle_retains_upstream_mit_notice(self) -> None:
        notice = (BUNDLE / "UPSTREAM_LICENSE").read_text()
        manifest = (BUNDLE / "bundle.json").read_text()
        self.assertIn("Copyright (c) 2026 Matt Pocock", notice)
        self.assertIn("6654f6b60cd9d5be8b54c6fafe44346dabeb3b76", manifest)


if __name__ == "__main__":
    unittest.main()
