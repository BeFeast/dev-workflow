# Grilling contract v1

`grilling` is the model-invoked primitive. `grill-me` is a user-invoked wrapper
that delegates to it; callers must not copy or fork the interview logic.

## Design tree

- A decision has a stable `snake_case` id, prompt, choices, recommendation,
  decision prerequisites, and optional discoverable-fact prerequisites.
- Resolve facts from the environment before asking the user. Facts do not
  become user decisions.
- The frontier contains every unresolved decision whose decision and fact
  prerequisites are settled.
- Preserve source order inside a frontier so generated calls and fixtures are
  deterministic.

## Frontier round

1. Snapshot the complete frontier before invoking a harness tool.
2. Partition that immutable snapshot only when the harness limits one call.
3. Collect and normalize every answer from every partition, including custom
   `Other` values and notes appended to a selected option. Discard a native
   `Other` sentinel, never the user's free-form text.
4. Commit only the complete snapshot. Never expose decisions unblocked by a
   partial partition.
5. Recompute the frontier and repeat.

The session ends only after every known decision is settled and the user
confirms shared understanding through the same interaction surface. A frontier
temporarily empty because facts are still being resolved is not completion. A
rejection or custom concern extends the tree. Do not implement the grilled plan
before confirmation.

## Adapter seam

An adapter may only:

- detect whether its real native questionnaire tool is callable in the active
  harness and mode;
- serialize a frontier snapshot within that tool's schema and call limits;
- normalize native and custom answers into the canonical answer shape;
- state the unavailable capability and use the documented fallback.

The Codex adapter further constrains each native question prompt to one
sentence and each option description to one short sentence, regardless of the
more permissive prose shape in the upstream skill. Its two or three choices
must be mutually exclusive; this semantic requirement stays in the skill and
fixtures because a serializer cannot infer exclusivity from arbitrary prose.

An adapter must not invent a neutral tool name, change the frontier, answer for
the user, silently claim native interaction, or recompute between chunks.
