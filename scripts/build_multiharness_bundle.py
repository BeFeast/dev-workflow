#!/usr/bin/env python3
"""Build or verify one deterministic portable multi-harness bundle."""

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
)


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify", type=Path)
    args = parser.parse_args()
    try:
        if args.output is not None:
            manifest = build_portable_bundle(args.output)
            print(
                f"built {len(manifest['files'])} payload files for "
                f"{len(manifest['harnesses'])} harnesses"
            )
        else:
            manifest = verify_portable_bundle(args.verify)
            print(f"verified {len(manifest['files'])} portable payload files")
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
