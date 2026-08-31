#!/usr/bin/env python3
"""Generate or verify the deterministic Claude Code skill bundle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dev_workflow.generated_claude import generated_files  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "harnesses" / "claude",
    )
    args = parser.parse_args()

    failures: list[str] = []
    for relative, expected in generated_files().items():
        target = args.output / relative
        if args.check:
            if not target.is_file():
                failures.append(f"missing generated file: {target}")
            elif target.read_text(encoding="utf-8") != expected:
                failures.append(f"stale generated file: {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(expected, encoding="utf-8")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    action = "verified" if args.check else "generated"
    print(f"{action} {len(generated_files())} Claude bundle files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
