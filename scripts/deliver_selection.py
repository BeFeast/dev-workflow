#!/usr/bin/env python3
"""Deliver or roll back a linked selection across the pinned harness roots.

This CLI verifies the release checksum against the supplied exact-SHA bundle
before installing, then delegates to the receipt-owned delivery orchestrator.
Targets are read from a runtime-supplied document; no path is embedded here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dev_workflow.deliver import deliver_selection, rollback_selection  # noqa: E402
from dev_workflow.multiharness import verify_release  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--targets", type=Path)
    parser.add_argument("--skill", action="append")
    args = parser.parse_args()

    try:
        if args.rollback:
            report = rollback_selection(args.state_dir)
            removed = report["removed"]
            summary = "; ".join(
                f"{harness}: {', '.join(skills)}" for harness, skills in removed.items()
            )
            print(f"rolled back {summary}")
            return 0

        for name in ("bundle_root", "release", "targets", "skill"):
            if getattr(args, name) is None:
                parser.error(f"--{name.replace('_', '-')} is required for delivery")
        recorded = json.loads(args.release.read_text(encoding="utf-8"))
        source_commit = recorded.get("source", {}).get("commit")
        if not isinstance(source_commit, str):
            raise ValueError("release descriptor is missing a source commit")
        release = verify_release(args.bundle_root, args.release, source_commit)
        targets_document = json.loads(args.targets.read_text(encoding="utf-8"))
        journal = deliver_selection(
            args.bundle_root,
            targets_document,
            args.skill,
            args.state_dir,
            release=release,
        )
        summary = "; ".join(
            f"{harness}: {', '.join(skills)}"
            for harness, skills in journal["delivered"].items()
        )
        print(f"delivered {summary}")
    except (FileExistsError, FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
