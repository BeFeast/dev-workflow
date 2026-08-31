from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dev_workflow.generated_opencode import generated_files
from scripts.validate_skills import parse_frontmatter, validate_skill


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "harnesses" / "opencode"


class OpenCodeGenerationTests(unittest.TestCase):
    def test_committed_bundle_is_current(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/generate_opencode_skills.py", "--check"],
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
                        "scripts/generate_opencode_skills.py",
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

    def test_wrapper_and_primitive_are_linked_and_opencode_specific(self) -> None:
        wrapper = (BUNDLE / "skills/grill-me/SKILL.md").read_text()
        primitive = (BUNDLE / "skills/grilling/SKILL.md").read_text()
        self.assertIn("linked `grilling` skill", wrapper)
        self.assertIn("OpenCode's `skill` tool", wrapper)
        self.assertNotIn("request_user_input", wrapper)
        self.assertIn("exact `question` tool", primitive)
        self.assertIn("ordered `string[][]`", primitive)
        self.assertIn("`multiple`", primitive)
        self.assertIn("do not assume `opencode run`", primitive)
        self.assertIn("Snapshot the complete frontier", primitive)
        self.assertIn("explicit confirmation", primitive)

    def test_bundle_packages_linked_dependency_and_notice(self) -> None:
        manifest = json.loads((BUNDLE / "bundle.json").read_text())
        self.assertEqual(manifest["harness"], "opencode")
        self.assertEqual(manifest["skills"]["grill-me"]["requires"], ["grilling"])
        self.assertEqual(manifest["skills"]["grilling"]["requires"], [])
        self.assertTrue((BUNDLE / "skills/grill-me/SKILL.md").is_file())
        self.assertTrue((BUNDLE / "skills/grilling/SKILL.md").is_file())
        self.assertIn(
            "Copyright (c) 2026 Matt Pocock",
            (BUNDLE / "UPSTREAM_LICENSE").read_text(),
        )

    def test_discoverability_in_isolated_opencode_project_root(self) -> None:
        binary = shutil.which("opencode")
        if binary is None:
            self.skipTest("opencode is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            target = project / ".opencode" / "skills"
            target.parent.mkdir(parents=True)
            shutil.copytree(BUNDLE / "skills", target)
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(root / "home"),
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_CACHE_HOME": str(root / "cache"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_STATE_HOME": str(root / "state"),
                    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
                    "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
                }
            )
            result = subprocess.run(
                [binary, "debug", "skill", "--pure"],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            skills = json.loads(result.stdout)
            found = {item["name"]: item for item in skills}
            self.assertIn("grill-me", found)
            self.assertIn("grilling", found)
            self.assertIn(
                ".opencode/skills/grill-me/SKILL.md",
                found["grill-me"]["location"],
            )
            self.assertIn(
                ".opencode/skills/grilling/SKILL.md",
                found["grilling"]["location"],
            )


if __name__ == "__main__":
    unittest.main()
