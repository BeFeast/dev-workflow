---
name: grilling
description: Interview the user relentlessly about a plan, decision, or idea through Claude Code's AskUserQuestion UI. Use for grill requests and when another skill delegates to the reusable grilling primitive.
user-invocable: false
---

# Grilling

Treat the subject as a design tree. Each decision may unlock later decisions.
The frontier is every unresolved decision whose prerequisites are settled.

## Build the frontier

1. Resolve discoverable facts from the filesystem, tools, or other available
   evidence. Never ask the user for a fact you can establish safely.
2. Keep unresolved fact lookups as prerequisites; ask the rest of the frontier
   while independent facts are being resolved.
3. Give every decision a stable `snake_case` id, a short header, two to four
   concrete choices, a concise trade-off per choice, and your recommendation.
   Keep decisions with unsettled prerequisites out of the current frontier.
4. Snapshot the complete frontier before asking any question.

The decisions are the user's. Never select an answer for them.

## Select the active surface

Inspect the tools and permission instructions in the active Claude Code
session. Use `AskUserQuestion` only when that exact tool is exposed and allowed.
Do not infer availability merely because this skill names the tool.

When native interaction is unavailable or a call is denied, state exactly which
capability is absent or denied and use the text fallback below. Never describe a
text response as the native questionnaire UI. If denial occurs after part of a
snapshot was answered, retain those answers and ask only the unanswered portion
of that same snapshot through the fallback before committing the round.

## Ask a native Claude Code round

- Send one to four questions per `AskUserQuestion` call.
- Give each question exactly the supported `question`, `header`, `options`, and
  `multiSelect` fields. End the question with `?` and keep the header at most 12
  characters.
- Give each question two to four distinct options with 1-5 word labels and a
  concise description of the impact or trade-off.
- Use `multiSelect: false` for mutually exclusive decisions. Use
  `multiSelect: true` only when selecting several non-exclusive choices is the
  decision being made, and phrase the question accordingly.
- Put the recommended option first and suffix its label with `(Recommended)`.
  Keep its base label to at most four words so the suffix stays within five.
- Do not add an `Other` option; Claude Code supplies the free-form escape.

AskUserQuestion keys returned answers by question text and returns multi-select
answers as comma-separated strings. Preserve custom Other text, optional
free-form `response`, and annotation notes. Never discard user-authored text.

If the frontier snapshot has more than four questions, partition that snapshot
into ordered chunks of at most four. Collect every chunk before applying any
answer or recomputing the tree. A partial chunk must never expose new decisions.

## Use the unavailable-tool fallback

State `Native questionnaire unavailable: <reason>.` Then render the same
snapshotted questions as a compact numbered list with choices, trade-offs,
recommendations, and an explicit custom-answer escape. Wait for one answer per
question. Preserve the immutable-snapshot rule even though text has no native
call limit.

## Keep clarification separate from plan approval

Use `AskUserQuestion` only for requirements, design choices, and the interview's
shared-understanding check. Never use it to ask whether a plan may be executed.
Never use `ExitPlanMode` for ordinary grilling questions.

After each complete round, record the user's decisions, reshape the tree, and
recompute the frontier. Repeat without a fixed question limit.

When every known decision is settled, use the same active questionnaire surface
for one final question: `Have we reached a complete shared understanding?`
Offer `Confirmed (Recommended)` and `Reopen` with `multiSelect: false`. Do not
treat a temporarily empty frontier blocked on fact lookup as completion. Reopen
or a custom concern extends the tree and resumes the rounds.

`Confirmed` completes only the interview; it is not approval to execute a plan.
In plan mode, once the interview and plan are ready, call `ExitPlanMode`
separately as Claude Code requires. Do not implement before both the interview
confirmation and any required plan-mode approval.
