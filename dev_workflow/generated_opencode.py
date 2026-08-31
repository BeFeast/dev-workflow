"""Deterministic source for the generated OpenCode skill pair."""

from __future__ import annotations

import json


UPSTREAM_COMMIT = "6654f6b60cd9d5be8b54c6fafe44346dabeb3b76"

UPSTREAM_LICENSE = """MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


GRILL_ME_SKILL = """---
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
"""


GRILLING_SKILL = """---
name: grilling
description: Interview the user relentlessly about a plan, decision, or idea through OpenCode's native question tool. Use for grill requests and when another skill delegates to the reusable grilling primitive.
---

# Grilling

Treat the subject as a design tree. Each decision may unlock later decisions.
The frontier is every unresolved decision whose prerequisites are settled.

## Build the frontier

1. Resolve discoverable facts from the filesystem, tools, or other available
   evidence. Never ask the user for a fact you can establish safely.
2. Keep unresolved fact lookups as prerequisites; ask the rest of the frontier
   while independent facts are being resolved.
3. Give every decision a stable `snake_case` id, a header of at most 30
   characters, concrete choices, concise trade-offs, and your recommendation.
   Keep decisions with unsettled prerequisites out of the current frontier.
4. Snapshot the complete frontier before asking any question.

The decisions are the user's. Never select an answer for them.

## Probe the active OpenCode surface

Inspect the current session's exposed tools, effective `question` permission,
and connected client response surface. Record the installed version with
`opencode --version` when that command is safely available. Use native
interaction only when the exact `question` tool is exposed, permission does not
deny it, and a response transport is attached.

Treat these as observed capabilities, not version or command-name guesses. In
particular, do not assume `opencode run` always allows or always denies
questions. If a tool call is rejected or the capability disappears, state the
observed reason and switch to the fallback without treating rejection as an
answer.

## Ask one native OpenCode round

Submit the entire frontier snapshot in one `question` call. Preserve frontier
order in the `questions` array. For each entry use exactly:

- `question`: the complete prompt;
- `header`: the short display header;
- `options`: objects with `label` and `description`;
- `multiple`: `true` only when the decision permits several simultaneous
  choices, otherwise `false`.

Put the recommended option first and suffix its label with `(Recommended)`.
Keep option labels to at most five words after adding the suffix. Do not add an
`Other` option and do not send a `custom` field: the current question tool
adds its custom-answer UI by default and its model-call schema does not accept
that field.

OpenCode keeps the native ordered `string[][]` only in internal tool metadata;
the model does not receive an `answers` object. The model-facing tool result is
a string in this shape:

`User has answered your questions: "<prompt>"="<answer>", "<next
prompt>"="<answer>". You can now continue with the user's answers in mind.`

Read those quoted prompt/answer entries in the original submitted question
order. For `multiple: true`, OpenCode has already joined selected labels with
comma-space inside that question's answer; preserve the surfaced order but do
not claim access to the original inner array. Preserve custom text as surfaced.
Treat `Unanswered`, a missing entry, an order mismatch, or a malformed result
as incomplete rather than inventing an answer. Before associating entries,
verify that every expected next-question boundary and the final result
terminator occurs exactly once. More than one occurrence is ambiguous custom
text, not a second decision; reject the round without remapping it. Apply
answers only after the complete snapshot is represented, then reshape the tree
and recompute the frontier.

## Use the unavailable-tool fallback

State `Native questionnaire unavailable: <observed reason>.` Then render the
same snapshot as a compact numbered list with choices, trade-offs,
recommendations, multi-select guidance where applicable, and an explicit
custom-answer escape. Wait for one answer per question. Never describe this
text exchange as OpenCode's native questionnaire.

## Continue and confirm

Repeat complete frontier rounds without a fixed question limit. A frontier
temporarily empty because fact lookup remains unresolved is not completion.

When every known decision is settled, use the same active surface for one final
single-select question: `Have we reached a complete shared understanding?`
Offer `Confirmed (Recommended)` and `Reopen`. A Reopen or custom concern extends
the tree and resumes the rounds. Stop only on explicit confirmation, and do not
act on the grilled plan before it arrives.
"""


def manifest_text() -> str:
    value = {
        "schema_version": 1,
        "harness": "opencode",
        "upstream": {
            "repository": "mattpocock/skills",
            "commit": UPSTREAM_COMMIT,
            "license": "MIT",
            "copyright": "Copyright (c) 2026 Matt Pocock",
        },
        "skills": {
            "grill-me": {
                "path": "skills/grill-me",
                "invocation": "user",
                "requires": ["grilling"],
            },
            "grilling": {
                "path": "skills/grilling",
                "invocation": "model",
                "requires": [],
            },
        },
    }
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def generated_files() -> dict[str, str]:
    return {
        "skills/grill-me/SKILL.md": GRILL_ME_SKILL,
        "skills/grilling/SKILL.md": GRILLING_SKILL,
        "bundle.json": manifest_text(),
        "UPSTREAM_LICENSE": UPSTREAM_LICENSE,
    }
