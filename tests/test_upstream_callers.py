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
    "grill-with-docs": {
        "blob": "62b9efb6f991d1b229adee7506962f13ced0c499",
        "operative_call": (
            'Call the Skill tool twice, for "grilling" and "domain-modeling".'
        ),
        "path": "skills/engineering/grill-with-docs/SKILL.md",
        "required_skill_calls": ["grilling", "domain-modeling"],
    },
    "improve-codebase-architecture": {
        "blob": "a578dd0a34ad0a8886abe7e7642b100106ba86d6",
        "operative_call": (
            'Once the user picks a candidate, call the Skill tool with "grilling" '
            "to walk the decision tree with them: constraints, dependencies, the "
            "shape of the deepened module, what sits behind the seam, what tests "
            "survive."
        ),
        "path": "skills/engineering/improve-codebase-architecture/SKILL.md",
        "required_skill_calls": ["codebase-design", "grilling", "domain-modeling"],
    },
    "triage": {
        "blob": "37ddea1e3dcf8fb5be5b92e4e45f2c34b8e61d3e",
        "operative_call": (
            'If the request needs fleshing out, call the Skill tool twice, for '
            '"grilling" and "domain-modeling", and grill it into shape a round '
            "of questions at a time, sharpening domain terms and updating "
            "`CONTEXT.md`/ADRs inline as decisions land."
        ),
        "path": "skills/engineering/triage/SKILL.md",
        "required_skill_calls": ["grilling", "domain-modeling"],
        "sibling_docs_are_caller_owned": True,
    },
    "wayfinder": {
        "blob": "812805b760baf328db0ebdef6f3807e381f97016",
        "operative_call": (
            "Grilling (HITL): Conversation. The default case. Always call the Skill "
            'tool twice, for "grilling" and "domain-modeling".'
        ),
        "path": "skills/engineering/wayfinder/SKILL.md",
        "required_skill_calls": [
            "research",
            "prototype",
            "grilling",
            "domain-modeling",
        ],
    },
}


class UpstreamCallerCompatibilityTests(unittest.TestCase):
    def test_fixture_pins_exact_upstream_callers_and_grilling_primitive(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            fixture["upstream"]["commit"],
            "6654f6b60cd9d5be8b54c6fafe44346dabeb3b76",
        )
        self.assertEqual(fixture["callers"], EXPECTED_CALLERS)
        self.assertEqual(
            fixture["grilling_primitive"]["blob"],
            "8ca78c6d8f901aab0c5a1f896034b70e666ff2a3",
        )
        self.assertEqual(
            fixture["grilling_primitive"]["path"],
            "skills/productivity/grilling/SKILL.md",
        )
        self.assertEqual(fixture["grilling_primitive"]["semantic_name"], "grilling")
        for name, caller in fixture["callers"].items():
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
        excluded = set(EXPECTED_CALLERS) | {
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
