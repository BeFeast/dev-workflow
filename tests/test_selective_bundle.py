from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dev_workflow.bundle import materialize_fixture, resolve_skills


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "harnesses" / "codex"


class SelectiveBundleTests(unittest.TestCase):
    def test_selecting_wrapper_includes_model_invoked_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installed = materialize_fixture(BUNDLE, Path(temporary), ["grill-me"])
            self.assertEqual(installed, ("grilling", "grill-me"))
            self.assertTrue((Path(temporary) / "grill-me/SKILL.md").is_file())
            self.assertTrue((Path(temporary) / "grilling/SKILL.md").is_file())

    def test_selecting_primitive_does_not_invent_reverse_dependency(self) -> None:
        manifest = json.loads((BUNDLE / "bundle.json").read_text())
        self.assertEqual(resolve_skills(manifest, ["grilling"]), ("grilling",))


if __name__ == "__main__":
    unittest.main()
