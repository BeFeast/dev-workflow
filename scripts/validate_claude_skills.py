#!/usr/bin/env python3
"""Validate the Claude-only invocation frontmatter and linked skill roles.

The generic Agent Skills/Codex quick validator rejects Claude Code's runtime
keys.  This validator deliberately requires those native keys so validation
cannot make the generated bundle less correct for Claude Code.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


FRONTMATTER = re.compile(r"^---\n(?P<body>.*?)\n---\n", re.DOTALL)


def parse_frontmatter(skill: Path) -> tuple[dict[str, object], str]:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    if not match:
        raise ValueError(f"{skill}: missing or malformed frontmatter")
    values: dict[str, object] = {}
    for line in match.group("body").splitlines():
        key, separator, raw_value = line.partition(":")
        if not separator or not key.strip() or not raw_value.strip():
            raise ValueError(f"{skill}: unsupported frontmatter line {line!r}")
        value: object = raw_value.strip()
        if value == "true":
            value = True
        elif value == "false":
            value = False
        values[key.strip()] = value
    return values, text[match.end() :]


def validate_bundle(root: Path) -> list[str]:
    errors: list[str] = []
    expectations = {
        "grill-me": {
            "name": "grill-me",
            "disable-model-invocation": True,
        },
        "grilling": {
            "name": "grilling",
            "user-invocable": False,
        },
    }
    parsed: dict[str, tuple[dict[str, object], str]] = {}
    for name, required in expectations.items():
        skill = root / "skills" / name
        try:
            frontmatter, body = parse_frontmatter(skill)
        except (OSError, ValueError) as error:
            errors.append(str(error))
            continue
        parsed[name] = (frontmatter, body)
        allowed = {"name", "description", *required.keys()}
        if set(frontmatter) != allowed:
            errors.append(
                f"{skill}: expected frontmatter keys {sorted(allowed)}, "
                f"got {sorted(frontmatter)}"
            )
        for key, value in required.items():
            if frontmatter.get(key) != value:
                errors.append(f"{skill}: {key} must be {value!r}")
        if not isinstance(frontmatter.get("description"), str):
            errors.append(f"{skill}: description must be a string")

    wrapper = parsed.get("grill-me")
    primitive = parsed.get("grilling")
    if wrapper and "`Skill` tool with `grilling`" not in wrapper[1]:
        errors.append("grill-me: wrapper must invoke the linked grilling primitive")
    if primitive and "AskUserQuestion" not in primitive[1]:
        errors.append("grilling: primitive must own AskUserQuestion behavior")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    errors = validate_bundle(args.root)
    if errors:
        print("\n".join(errors))
        return 1
    print("validated Claude user-only wrapper and model-only primitive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
