#!/usr/bin/env python3
"""Build or verify one deterministic portable multi-harness bundle.

With ``--commit``/``--release`` the builder also emits or verifies a
``release.json`` binding that ties a full source commit to the deterministic
bundle checksum and the retained upstream attribution.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dev_workflow.multiharness import (  # noqa: E402
    build_portable_bundle,
    verify_portable_bundle,
    verify_release,
    write_release,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify", type=Path)
    parser.add_argument("--commit", help="Full source commit to bind in release.json.")
    parser.add_argument(
        "--release",
        type=Path,
        help="Path to the release binding to emit (with --output) or verify (with --verify).",
    )
    args = parser.parse_args()
    if (args.commit is None) != (args.release is None):
        parser.error("--commit and --release must be provided together")
    try:
        if args.output is not None:
            manifest = build_portable_bundle(args.output)
            print(
                f"built {len(manifest['files'])} payload files for "
                f"{len(manifest['harnesses'])} harnesses"
            )
            if args.commit is not None:
                descriptor = write_release(args.output, args.release, args.commit)
                print(f"release {descriptor['version']} checksum {descriptor['bundle']['checksum']}")
        else:
            manifest = verify_portable_bundle(args.verify)
            print(f"verified {len(manifest['files'])} portable payload files")
            if args.commit is not None:
                descriptor = verify_release(args.verify, args.release, args.commit)
                print(f"verified release {descriptor['version']} for {args.commit}")
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
