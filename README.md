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
