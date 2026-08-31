from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from dev_workflow.multiharness import build_portable_bundle


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/upstream-callers.json"
EXPECTED_CALLERS = {
    "grill-with-docs",
    "triage",
    "wayfinder",
    "improve-codebase-architecture",
}


class UpstreamCallerCompatibilityTests(unittest.TestCase):
    def test_fixture_pins_exact_upstream_callers_and_grilling_primitive(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            fixture["upstream"]["commit"],
            "6654f6b60cd9d5be8b54c6fafe44346dabeb3b76",
        )
        self.assertEqual(set(fixture["callers"]), EXPECTED_CALLERS)
        self.assertEqual(
            fixture["grilling_primitive"]["blob"],
            "8ca78c6d8f901aab0c5a1f896034b70e666ff2a3",
        )
        for name, caller in fixture["callers"].items():
            self.assertRegex(caller["blob"], r"^[0-9a-f]{40}$", name)
            self.assertIn("grilling", caller["required_skill_calls"])
            self.assertRegex(
                caller["operative_call"],
                re.compile(r"Skill tool[^\n]*\"grilling\"", re.IGNORECASE),
                name,
            )

    def test_every_harness_satisfies_model_invoked_grilling_edge(self) -> None:
        spellings = {
            "codex": "model-invoked `$grilling` skill",
            "claude": "`Skill` tool with `grilling`",
            "opencode": "OpenCode's `skill` tool",
        }
        for harness, spelling in spellings.items():
            bundle = ROOT / "harnesses" / harness
            manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["skills"]["grilling"]["invocation"], "model")
            self.assertEqual(manifest["skills"]["grilling"]["requires"], [])
            wrapper = (bundle / "skills/grill-me/SKILL.md").read_text(encoding="utf-8")
            primitive = (bundle / "skills/grilling/SKILL.md").read_text(encoding="utf-8")
            self.assertIn(spelling, wrapper)
            self.assertRegex(primitive, re.compile(r"\bWait\b", re.IGNORECASE))
            self.assertRegex(primitive, re.compile(r"\bRepeat\b", re.IGNORECASE))
            self.assertIn("confirmation", primitive.casefold())

    def test_default_portable_artifact_does_not_bundle_callers_or_siblings(self) -> None:
        excluded = EXPECTED_CALLERS | {
            "domain-modeling",
            "codebase-design",
            "research",
            "prototype",
            "AGENT-BRIEF.md",
            "OUT-OF-SCOPE.md",
        }
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "artifact"
            manifest = build_portable_bundle(artifact)
            self.assertEqual(
                set(manifest["harnesses"]), {"codex", "claude", "opencode"}
            )
            for relative in manifest["files"]:
                self.assertTrue(
                    all(name not in relative for name in excluded), relative
                )
            for harness in manifest["harnesses"]:
                harness_manifest = json.loads(
                    (artifact / f"harnesses/{harness}/bundle.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    set(harness_manifest["skills"]), {"grill-me", "grilling"}
                )


if __name__ == "__main__":
    unittest.main()
