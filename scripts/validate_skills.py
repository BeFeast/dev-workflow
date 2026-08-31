#!/usr/bin/env python3
"""Dependency-free repository gate mirroring quick skill validation."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


FRONTMATTER = re.compile(r"^---\n(?P<body>.*?)\n---\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER.match(text)
    if not match:
        raise ValueError("missing or malformed YAML frontmatter")
    result: dict[str, str] = {}
    for line in match.group("body").splitlines():
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"unsupported frontmatter line: {line!r}")
        result[key.strip()] = value.strip()
    return result


def validate_skill(path: Path) -> list[str]:
    errors: list[str] = []
    skill_md = path / "SKILL.md"
    if not skill_md.is_file():
        return [f"{path}: SKILL.md not found"]
    text = skill_md.read_text(encoding="utf-8")
    try:
        frontmatter = parse_frontmatter(text)
    except ValueError as error:
        return [f"{path}: {error}"]
    if set(frontmatter) != {"name", "description"}:
        errors.append(f"{path}: frontmatter must contain exactly name and description")
    name = frontmatter.get("name", "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        errors.append(f"{path}: invalid skill name {name!r}")
    if name != path.name:
        errors.append(f"{path}: folder and skill name differ")
    description = frontmatter.get("description", "")
    if not description or len(description) > 1024 or "<" in description or ">" in description:
        errors.append(f"{path}: invalid skill description")
    if len(text.splitlines()) > 500:
        errors.append(f"{path}: SKILL.md exceeds 500 lines")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    errors = [error for path in args.paths for error in validate_skill(path)]
    if errors:
        print("\n".join(errors))
        return 1
    print(f"validated {len(args.paths)} skill folders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
