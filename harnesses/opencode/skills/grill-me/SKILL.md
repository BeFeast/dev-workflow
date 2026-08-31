---
name: grill-me
description: Start a native, relentless interview that sharpens a plan, decision, or design. Use only when the user explicitly invokes grill-me or asks to be grilled.
---

# Grill Me

Load the linked `grilling` skill through OpenCode's `skill` tool and give it
the current conversation as its subject. Keep this user-invoked wrapper thin;
all interview behavior belongs to the model-invoked primitive.

If `grilling` is missing, stop and report that the linked skill bundle is
incomplete. Do not reconstruct the primitive from memory. Do not implement the
result until `grilling` obtains explicit shared-understanding confirmation.
