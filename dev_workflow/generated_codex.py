"""Deterministic source for the generated Codex skill pair."""

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

Invoke the linked model-invoked `$grilling` skill with the current conversation
as its subject. Keep this wrapper thin; all interview behavior belongs to that
primitive.

If `$grilling` is missing, stop and report that the linked skill bundle is
incomplete. Do not reconstruct the primitive from memory. Do not implement the
result until `$grilling` obtains explicit shared-understanding confirmation.
"""


GRILLING_SKILL = """---
name: grilling
description: Interview the user relentlessly about a plan, decision, or idea through Codex's native questionnaire UI. Use for grill requests and when another skill delegates to the reusable grilling primitive.
---

# Grilling

Treat the subject as a design tree. Each decision may unlock later decisions.
The frontier is every unresolved decision whose prerequisites are settled.

## Build the frontier

1. Resolve discoverable facts from the filesystem, tools, or other available
   evidence. Never ask the user for a fact you can establish safely.
2. Keep unresolved fact lookups as prerequisites; ask the rest of the frontier
   while independent facts are being resolved.
3. Give every decision a stable `snake_case` id, a short header, two or three
   concrete choices, a concise trade-off per choice, and your recommendation.
   Keep decisions with unsettled prerequisites out of the current frontier.
4. Snapshot the complete frontier before asking any question.

The decisions are the user's. Never select an answer for them.

## Select the active surface

Inspect the tools and collaboration-mode instructions in the current session.
Use `request_user_input` only when that exact tool is exposed and the current
mode permits the call. Do not assume availability merely because this skill
names the tool.

When native interaction is unavailable, say exactly which capability is absent
or denied, then use the text fallback below. Never describe a text response as
the native questionnaire UI.

## Ask a native Codex round

- Send one to three questions per `request_user_input` call.
- Write each question prompt as exactly one short sentence. Use a header of at
  most 12 characters, a stable `snake_case` id, and two or three options with
  1-5 word labels.
- Make the two or three choices mutually exclusive. Give each choice one short
  sentence that explains its impact or trade-off.
- Put the recommended option first and suffix its label with `(Recommended)`.
- Keep the recommended base label to at most four words so the suffix stays
  within the five-word label limit.
- Do not add an `Other` option; the native client supplies the free-form escape.

If the frontier snapshot has more than three questions, partition that snapshot
into ordered chunks of at most three. Collect every chunk before applying any
answer or recomputing the tree. Normalize selected options and free-form Other
answers only after the whole snapshot is answered. Preserve appended native
notes. For an Other response, discard only the native sentinel and keep all of
the user's free-form text.

## Use the unavailable-tool fallback

State `Native questionnaire unavailable: <reason>.` Then render the same
snapshotted questions as a compact numbered list with choices, trade-offs,
recommendations, and an explicit custom-answer escape. Wait for one answer per
question. For a frontier larger than three, keep the same immutable-snapshot
rule even though the fallback is not constrained by the native call limit.

## Continue and confirm

After the whole round is answered, record the user's decisions, reshape the
tree, and recompute the frontier. Repeat without a fixed question limit.

When every known decision is settled, use the same active surface for one final question.
Do not treat a temporarily empty frontier blocked on fact lookup as completion.
Ask:
`Have we reached a complete shared understanding?` Offer `Confirmed
(Recommended)` and `Reopen`. A Reopen or custom concern extends the design tree
and resumes the rounds. Stop only on explicit confirmation, and do not act on
the grilled plan before it arrives.
"""


GRILL_ME_OPENAI = """interface:
  display_name: "Grill Me"
  short_description: "Start a native decision-tree interview"
  default_prompt: "Use $grill-me to interview me until our plan is fully understood."
policy:
  allow_implicit_invocation: false
"""


GRILLING_OPENAI = """interface:
  display_name: "Grilling"
  short_description: "Run reusable native questionnaire rounds"
  default_prompt: "Use $grilling to stress-test this plan through native questionnaire rounds."
policy:
  allow_implicit_invocation: true
"""


def manifest_text() -> str:
    value = {
        "schema_version": 1,
        "harness": "codex",
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
        "skills/grill-me/agents/openai.yaml": GRILL_ME_OPENAI,
        "skills/grilling/SKILL.md": GRILLING_SKILL,
        "skills/grilling/agents/openai.yaml": GRILLING_OPENAI,
        "bundle.json": manifest_text(),
        "UPSTREAM_LICENSE": UPSTREAM_LICENSE,
    }
