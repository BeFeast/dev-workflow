"""Claude Code serialization for the canonical grilling contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import AbstractSet, Mapping, Sequence

from .grilling import Option, Question, RoundSnapshot


CLAUDE_MAX_QUESTIONS = 4
CLAUDE_MAX_OPTIONS = 4
OTHER_SENTINELS = frozenset({"other", "none of the above"})


class Surface(str, Enum):
    NATIVE = "AskUserQuestion"
    FALLBACK = "text-fallback"


class ConfirmationDisposition(str, Enum):
    CONFIRMED = "confirmed"
    REOPEN = "reopen"
    EXTEND = "extend"


@dataclass(frozen=True)
class ConfirmationResult:
    disposition: ConfirmationDisposition
    concern: str | None = None

    @property
    def may_finish_interview(self) -> bool:
        return self.disposition is ConfirmationDisposition.CONFIRMED

    @property
    def continue_interview(self) -> bool:
        return not self.may_finish_interview

    @property
    def extends_tree(self) -> bool:
        return self.disposition in {
            ConfirmationDisposition.REOPEN,
            ConfirmationDisposition.EXTEND,
        }


@dataclass(frozen=True)
class Capabilities:
    """Observed Claude Code capabilities, including permission-policy denial."""

    ask_user_question_exposed: bool
    ask_user_question_permitted: bool

    @property
    def surface(self) -> Surface:
        if self.ask_user_question_exposed and self.ask_user_question_permitted:
            return Surface.NATIVE
        return Surface.FALLBACK

    @property
    def fallback_reason(self) -> str | None:
        if not self.ask_user_question_exposed:
            return "AskUserQuestion is not exposed by the active Claude Code harness"
        if not self.ask_user_question_permitted:
            return "AskUserQuestion is denied by the active Claude Code permission policy"
        return None


def plan_chunks(snapshot: RoundSnapshot) -> tuple[tuple[Question, ...], ...]:
    """Chunk one already-captured frontier without recomputing it."""

    return snapshot.chunks(CLAUDE_MAX_QUESTIONS)


def _native_option(option: Option, recommended: bool) -> dict[str, str]:
    label = option.label
    if recommended and not label.endswith("(Recommended)"):
        label = f"{label} (Recommended)"
    return {"label": label, "description": option.description}


def serialize_native(
    questions: Sequence[Question],
    *,
    multi_select_ids: AbstractSet[str] = frozenset(),
) -> dict[str, list[dict[str, object]]]:
    """Build one exact AskUserQuestion payload from at most four questions."""

    if not 1 <= len(questions) <= CLAUDE_MAX_QUESTIONS:
        raise ValueError("Claude native chunks must contain one to four questions")
    question_ids = {question.id for question in questions}
    unknown_multi_select = set(multi_select_ids) - question_ids
    if unknown_multi_select:
        raise ValueError(
            f"multi-select ids are not in the submitted chunk: {sorted(unknown_multi_select)}"
        )
    prompts = [question.prompt for question in questions]
    if len(set(prompts)) != len(prompts):
        raise ValueError("Claude native question prompts must be unique within a chunk")

    payload: list[dict[str, object]] = []
    for question in questions:
        if len(question.header) > 12:
            raise ValueError(f"Claude header for {question.id!r} exceeds 12 characters")
        if not question.prompt.rstrip().endswith("?"):
            raise ValueError(f"Claude question for {question.id!r} must end with a question mark")
        if not 2 <= len(question.options) <= CLAUDE_MAX_OPTIONS:
            raise ValueError(f"Claude question {question.id!r} needs two to four options")
        labels = [option.label.strip() for option in question.options]
        if len({label.casefold() for label in labels}) != len(labels):
            raise ValueError(f"Claude option labels for {question.id!r} must be distinct")
        if any(label.casefold() in OTHER_SENTINELS for label in labels):
            raise ValueError(
                f"Claude question {question.id!r} must rely on the native Other option"
            )
        if any(not 1 <= len(label.split()) <= 5 for label in labels):
            raise ValueError(
                f"Claude option labels for {question.id!r} need one to five words"
            )

        ordered = (
            question.options[question.recommended],
            *(
                option
                for index, option in enumerate(question.options)
                if index != question.recommended
            ),
        )
        native_options = [
            _native_option(option, index == 0)
            for index, option in enumerate(ordered)
        ]
        if any(len(option["label"].split()) > 5 for option in native_options):
            raise ValueError(
                f"Claude option labels for {question.id!r} exceed five words "
                "after recommendation marking"
            )
        payload.append(
            {
                "question": question.prompt,
                "header": question.header,
                "options": native_options,
                "multiSelect": question.id in multi_select_ids,
            }
        )
    return {"questions": payload}


def _annotation_notes(
    annotations: Mapping[str, object], prompt: str
) -> str | None:
    annotation = annotations.get(prompt)
    if annotation is None:
        return None
    if not isinstance(annotation, Mapping):
        raise ValueError(f"Claude annotation for {prompt!r} must be a mapping")
    notes = annotation.get("notes")
    if notes is None:
        return None
    if not isinstance(notes, str) or not notes.strip():
        raise ValueError(f"Claude annotation notes for {prompt!r} must be non-empty")
    return notes.strip()


def _append_distinct(value: str, addition: str | None) -> str:
    if addition is None or addition == value or addition in value:
        return value
    return f"{value} — {addition}"


def normalize_native_response(
    questions: Sequence[Question], response: Mapping[str, object]
) -> dict[str, str]:
    """Normalize AskUserQuestion output into canonical id-keyed strings."""

    prompts = [question.prompt for question in questions]
    if len(set(prompts)) != len(prompts):
        raise ValueError("Claude native question prompts must be unique within a chunk")
    raw_answers = response.get("answers")
    if not isinstance(raw_answers, Mapping):
        raise ValueError("Claude response must contain an answers mapping")
    if set(raw_answers) != set(prompts):
        raise ValueError("Claude response questions do not match the submitted chunk")

    raw_annotations = response.get("annotations", {})
    if not isinstance(raw_annotations, Mapping):
        raise ValueError("Claude response annotations must be a mapping")
    unknown_annotations = set(raw_annotations) - set(prompts)
    if unknown_annotations:
        raise ValueError("Claude response annotations contain unknown questions")

    freeform = response.get("response")
    if freeform is not None and (not isinstance(freeform, str) or not freeform.strip()):
        raise ValueError("Claude free-form response must be a non-empty string")
    freeform = freeform.strip() if isinstance(freeform, str) else None

    sentinel_prompts: list[str] = []
    for prompt in prompts:
        value = raw_answers[prompt]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Claude answer for {prompt!r} must be a non-empty string")
        if value.strip().casefold() in OTHER_SENTINELS:
            sentinel_prompts.append(prompt)
    if freeform and len(questions) > 1 and len(sentinel_prompts) != 1:
        if freeform not in {str(value).strip() for value in raw_answers.values()}:
            raise ValueError("Claude free-form response cannot be assigned unambiguously")

    normalized: dict[str, str] = {}
    for question in questions:
        answer = str(raw_answers[question.prompt]).strip()
        notes = _annotation_notes(raw_annotations, question.prompt)
        if answer.casefold() in OTHER_SENTINELS:
            if freeform and (len(questions) == 1 or sentinel_prompts == [question.prompt]):
                answer = freeform
            elif notes:
                answer, notes = notes, None
            else:
                raise ValueError(
                    f"Claude Other answer for {question.prompt!r} has no free-form text"
                )
        elif freeform and len(questions) == 1:
            answer = _append_distinct(answer, freeform)
        answer = _append_distinct(answer, notes)
        normalized[question.id] = answer
    return normalized


def render_fallback(questions: Sequence[Question], reason: str) -> str:
    """Render a truthful text fallback for absent or denied native interaction."""

    lines = [f"Native questionnaire unavailable: {reason}.", ""]
    for index, question in enumerate(questions, start=1):
        lines.append(f"{index}. {question.header}: {question.prompt}")
        for option_index, option in enumerate(question.options):
            marker = " (Recommended)" if option_index == question.recommended else ""
            lines.append(f"   - {option.label}{marker}: {option.description}")
        lines.append("   - Other: provide a custom answer.")
    lines.extend(("", "Reply with one answer for every numbered question."))
    return "\n".join(lines)


def confirmation_question() -> Question:
    return Question(
        id="shared_understanding",
        header="Confirm",
        prompt="Have we reached a complete shared understanding?",
        options=(
            Option("Confirmed", "The interview is complete; stop asking questions."),
            Option("Reopen", "Add the missing concern to the design tree and continue."),
        ),
        recommended=0,
    )


def resolve_confirmation(value: str) -> ConfirmationResult:
    """Finish only the interview on explicit confirmation, never approve a plan."""

    answer = value.strip()
    if not answer:
        raise ValueError("confirmation answer must be non-empty")
    canonical = answer.removesuffix(" (Recommended)").removesuffix(" (recommended)")
    if canonical == "Confirmed":
        return ConfirmationResult(ConfirmationDisposition.CONFIRMED)
    if canonical == "Reopen":
        return ConfirmationResult(ConfirmationDisposition.REOPEN)
    return ConfirmationResult(ConfirmationDisposition.EXTEND, concern=answer)
