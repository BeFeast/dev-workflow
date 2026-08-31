---
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
answers only after the whole snapshot is answered.

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
