#!/usr/bin/env bash
# Approval-gated multi-harness delivery entrypoint.
#
# Every target and credential is resolved by the approved runtime environment.
# This script embeds no private endpoint, host path, or secret; it reads the
# install targets from a runtime-supplied document and refuses to run unless the
# runtime has set the explicit approval flag.
#
# Required environment (populated by the approved runtime):
#   DEV_WORKFLOW_DELIVER_APPROVED    Must equal "1"; the runtime approval gate.
#   DEV_WORKFLOW_DELIVERY_STATE_DIR  Directory holding the before-state journal.
#   DEV_WORKFLOW_INSTALL_TARGETS     Path to a runtime-input://dev-workflow/
#                                    install-targets-v1 document (install only).
# Optional environment:
#   DEV_WORKFLOW_SOURCE_SHA          Exact source commit to materialize (default HEAD).
#   DEV_WORKFLOW_SELECTED_SKILL      Linked skill to deliver (default grill-me).
#   DEV_WORKFLOW_REPO_ROOT           Override the repository root (testing seam).
#
# Usage:
#   scripts/deliver.sh             Install the pinned selection into every root.
#   scripts/deliver.sh --rollback  Remove only the links a prior delivery created.
set -euo pipefail

repo_root="${DEV_WORKFLOW_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

fail() {
  printf 'deliver: %s\n' "$1" >&2
  exit 2
}

rollback=0
case "${1:-}" in
  --rollback) rollback=1 ;;
  "") ;;
  *) fail "unknown argument: $1" ;;
esac

[ "${DEV_WORKFLOW_DELIVER_APPROVED:-}" = "1" ] \
  || fail "delivery is not approved by the runtime environment"
state_dir="${DEV_WORKFLOW_DELIVERY_STATE_DIR:-}"
[ -n "$state_dir" ] || fail "DEV_WORKFLOW_DELIVERY_STATE_DIR is required"

if [ "$rollback" -eq 1 ]; then
  exec python3 "$repo_root/scripts/deliver_selection.py" \
    --rollback --state-dir "$state_dir"
fi

targets="${DEV_WORKFLOW_INSTALL_TARGETS:-}"
[ -n "$targets" ] || fail "DEV_WORKFLOW_INSTALL_TARGETS is required"
[ -f "$targets" ] || fail "install targets document is missing: $targets"
skill="${DEV_WORKFLOW_SELECTED_SKILL:-grill-me}"

sha="${DEV_WORKFLOW_SOURCE_SHA:-$(git -C "$repo_root" rev-parse HEAD)}"
case "$sha" in
  "" | *[!0-9a-f]*) fail "source sha must be a full hex commit: $sha" ;;
esac
[ "${#sha}" -eq 40 ] || fail "source sha must be a full 40-character commit: $sha"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Materialize the exact source SHA into an isolated tree and build the release
# bundle there, so the delivered payload is bound to a reproducible commit.
git -C "$repo_root" archive "$sha" | tar -x -C "$work"
bundle="$work/bundle"
release="$work/release.json"
python3 "$work/scripts/build_multiharness_bundle.py" \
  --output "$bundle" --commit "$sha" --release "$release" >/dev/null

# Verify the release checksum from a second, independent exact-SHA materialization.
verify_src="$work/verify-src"
mkdir -p "$verify_src"
git -C "$repo_root" archive "$sha" | tar -x -C "$verify_src"
python3 "$verify_src/scripts/build_multiharness_bundle.py" \
  --verify "$bundle" --commit "$sha" --release "$release" >/dev/null

python3 "$repo_root/scripts/deliver_selection.py" \
  --bundle-root "$bundle" \
  --release "$release" \
  --targets "$targets" \
  --state-dir "$state_dir" \
  --skill "$skill"
