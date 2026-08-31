---
name: grill-me
description: Start a native, relentless interview that sharpens a plan, decision, or design. Use only when the user explicitly invokes grill-me or asks to be grilled.
disable-model-invocation: true
---

# Grill Me

Call the `Skill` tool with `grilling`, passing the current conversation as its
subject. Keep this wrapper thin; all interview behavior belongs to that linked
model-invoked primitive.

If `grilling` is missing, stop and report that the linked skill bundle is
incomplete. Do not reconstruct the primitive from memory. Do not implement the
result until `grilling` obtains explicit shared-understanding confirmation and,
in plan mode, Claude Code obtains separate approval through `ExitPlanMode`.
