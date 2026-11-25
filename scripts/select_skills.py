#!/usr/bin/env python3
"""Install or uninstall a linked selection in an isolated harness root."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dev_workflow.bundle import install_selection, uninstall_selection  # noqa: E402
from dev_workflow.multiharness import HARNESS_REGISTRY  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Operate only on an explicitly supplied isolated harness root."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    install = subparsers.add_parser("install")
    install.add_argument("--harness", choices=HARNESS_REGISTRY, required=True)
    install.add_argument("--root", type=Path, required=True)
    install.add_argument("--skill", action="append", required=True)
    install.add_argument(
        "--bundle-root",
        type=Path,
        default=ROOT / "harnesses",
        help="Repository harnesses directory or a built portable artifact.",
    )
    uninstall = subparsers.add_parser("uninstall")
    uninstall.add_argument("--harness", choices=HARNESS_REGISTRY, required=True)
    uninstall.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.action == "install":
            resolved = install_selection(
                args.bundle_root, args.root, args.harness, args.skill
            )
            print("installed: " + ", ".join(resolved))
        else:
            resolved = uninstall_selection(args.root, args.harness)
            print("uninstalled: " + ", ".join(resolved))
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
