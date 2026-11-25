#!/usr/bin/env python3
"""Materialize a dependency-complete Codex skill selection into an empty root."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dev_workflow.bundle import materialize_selection  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize a portable Codex selection. Use an isolated target; "
            "live installation is outside this command contract."
        )
    )
    parser.add_argument("--skill", action="append", required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()

    try:
        resolved = materialize_selection(
            ROOT / "harnesses" / "codex", args.target, args.skill
        )
    except (FileExistsError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print("materialized: " + ", ".join(resolved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
