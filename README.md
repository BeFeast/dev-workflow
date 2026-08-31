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
