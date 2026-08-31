from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        self.assertNotIn("request_user_input", wrapper)
        self.assertIn("`question` in OpenCode", primitive)
        self.assertIn("Map this as a **design tree**", primitive)
        self.assertNotIn("❓ **Q1**", primitive)
        command = (BUNDLE / "commands/grill-me.md").read_text()
        self.assertIn("Load the `grilling` skill", command)
        self.assertIn("$ARGUMENTS", command)

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
        binary = os.environ.get("DEV_WORKFLOW_OPENCODE_TEST_BINARY") or shutil.which(
            "opencode"
        )
        if binary is None:
            self.skipTest("opencode is not installed")
        binary = str(Path(binary).resolve())
        version = subprocess.run(
            [binary, "--version"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if version.returncode != 0 or version.stdout.strip() != "1.18.25":
            observed = (version.stdout or version.stderr).strip() or "unavailable"
            self.skipTest(
                "isolated discovery is pinned to the verified OpenCode 1.18.25 "
                f"surface; observed {observed}"
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            target = project / ".opencode" / "skills"
            target.parent.mkdir(parents=True)
            shutil.copytree(BUNDLE / "skills", target)
            self.assertEqual(
                sorted(
                    path.relative_to(target).as_posix()
                    for path in target.rglob("SKILL.md")
                ),
                ["grill-me/SKILL.md", "grilling/SKILL.md"],
            )

            # Review and CI runners commonly disable project config while
            # inspecting a repository. That ambient setting must not disable
            # the isolated project-local surface this probe is testing.
            contaminated = {
                "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
                "OPENCODE_CONFIG": str(root / "ambient-opencode.json"),
                "OPENCODE_CONFIG_CONTENT": '{"skills":{"paths":[]}}',
                "OPENCODE_CONFIG_DIR": str(root / "ambient-config"),
                "OPENCODE_FAKE_VCS": "git",
            }
            with mock.patch.dict(os.environ, contaminated, clear=False):
                env = os.environ.copy()
            for variable in (
                "OPENCODE_CONFIG",
                "OPENCODE_CONFIG_CONTENT",
                "OPENCODE_CONFIG_DIR",
                "OPENCODE_FAKE_VCS",
            ):
                env.pop(variable, None)
            env.update(
                {
                    "HOME": str(root / "home"),
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_CACHE_HOME": str(root / "cache"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_STATE_HOME": str(root / "state"),
                    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
                    "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
                    "OPENCODE_DISABLE_PROJECT_CONFIG": "0",
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
