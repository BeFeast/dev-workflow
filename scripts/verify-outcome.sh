#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python3 -m compileall -q dev_workflow scripts tests
python3 scripts/generate_codex_skills.py --check
python3 scripts/validate_skills.py \
  harnesses/codex/skills/grill-me \
  harnesses/codex/skills/grilling
python3 -m unittest discover -s tests -v

printf 'dev-workflow outcome verified\n'
