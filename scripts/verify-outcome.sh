#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

portable_tmp="$(mktemp -d)"
trap 'rm -rf "$portable_tmp"' EXIT

python3 -m compileall -q dev_workflow scripts tests
python3 scripts/generate_codex_skills.py --check
python3 scripts/generate_claude_skills.py --check
python3 scripts/generate_opencode_skills.py --check
python3 scripts/validate_skills.py \
  harnesses/codex/skills/grill-me \
  harnesses/codex/skills/grilling
python3 scripts/validate_claude_skills.py harnesses/claude
python3 scripts/validate_skills.py \
  harnesses/opencode/skills/grill-me \
  harnesses/opencode/skills/grilling
python3 scripts/build_multiharness_bundle.py --output "$portable_tmp/first"
python3 scripts/build_multiharness_bundle.py --output "$portable_tmp/second"
python3 scripts/build_multiharness_bundle.py --verify "$portable_tmp/first"
python3 scripts/build_multiharness_bundle.py --verify "$portable_tmp/second"
diff -qr "$portable_tmp/first" "$portable_tmp/second"

# Bind the current source commit to the deterministic bundle checksum and
# verify that binding, then reproduce the same checksum from an isolated
# exact-SHA materialization built by that commit's own tooling.
release_sha="$(git rev-parse HEAD)"
python3 scripts/build_multiharness_bundle.py \
  --output "$portable_tmp/release" \
  --commit "$release_sha" \
  --release "$portable_tmp/release.json"
python3 scripts/build_multiharness_bundle.py \
  --verify "$portable_tmp/release" \
  --commit "$release_sha" \
  --release "$portable_tmp/release.json"
mkdir -p "$portable_tmp/exact-sha"
git archive "$release_sha" | tar -x -C "$portable_tmp/exact-sha"
python3 "$portable_tmp/exact-sha/scripts/build_multiharness_bundle.py" \
  --output "$portable_tmp/exact-sha-bundle"
diff -q "$portable_tmp/release/manifest.json" "$portable_tmp/exact-sha-bundle/manifest.json"

python3 -m unittest discover -s tests -v

printf 'dev-workflow outcome verified\n'
