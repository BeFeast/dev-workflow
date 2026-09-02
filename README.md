# Dev Workflow

Native interactive questionnaire rounds replace Markdown-only grilling while preserving the complete linked grill-me -> grilling flow across Codex, Claude Code, and OpenCode.

Project: `BeFeast/dev-workflow`.

The first supported harness is Codex. Its committed bundle lives under
`harnesses/codex/`; `grill-me` remains a user-invoked wrapper over the reusable
model-invoked `grilling` primitive. The canonical frontier-round behavior is
defined in `contracts/grilling-v1.md` and enforced by the Python fixtures.

Run the complete repository gate with:

```sh
./scripts/verify-outcome.sh
```

The canonical single-path skill installer does not consume this repository's
`bundle.json`, so selecting only its `grill-me` path would omit `grilling` and
the upstream notice. Materialize a dependency-complete portable selection with
the repository selector instead:

```sh
python3 scripts/select_codex_skills.py \
  --skill grill-me \
  --target /tmp/dev-workflow-codex-selection
```

The target must be empty. This command is safe for isolated inspection and
fixture roots; live harness installation remains a separate approval-gated
delivery step.

## Release and delivery

`scripts/build_multiharness_bundle.py --output DIR --commit <sha> --release
release.json` binds a full source commit to the deterministic bundle checksum
and the retained upstream attribution. The same command with `--verify`
reproduces and checks that binding from an isolated exact-SHA materialization.

`scripts/deliver.sh` is the stable, approval-gated delivery entrypoint. It
resolves every target and credential from the approved runtime environment and
embeds no private endpoint, host path, or secret:

- `DEV_WORKFLOW_DELIVER_APPROVED=1` — the runtime approval gate (required).
- `DEV_WORKFLOW_INSTALL_TARGETS` — a `dev-workflow/install-targets-v1` document
  pinning the three harness roots.
- `DEV_WORKFLOW_DELIVERY_STATE_DIR` — where the before-state journal is written.

Delivery materializes the exact source SHA, verifies the release checksum,
installs only the intended linked skills into every pinned root, and records
the before-state. `scripts/deliver.sh --rollback` removes only the links that
delivery created and confirms the prior state is restored. A missing target
root fails closed before any byte is written.
