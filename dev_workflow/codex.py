"""Codex/T3 serialization for the canonical grilling contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Mapping, Sequence

from .grilling import Option, Question, RoundSnapshot


CODEX_MAX_QUESTIONS = 3
CODEX_MAX_OPTIONS = 3
CODEX_MAX_PROMPT_CHARS = 240
CODEX_MAX_DESCRIPTION_CHARS = 160
MULTIPLE_SENTENCES = re.compile(r"[.!?](?:[\"')\]]+)?\s+\S")


class Surface(str, Enum):
    NATIVE = "request_user_input"
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
    def may_act(self) -> bool:
        return self.disposition is ConfirmationDisposition.CONFIRMED

    @property
    def continue_interview(self) -> bool:
        return not self.may_act

    @property
    def extends_tree(self) -> bool:
        return self.disposition in {
            ConfirmationDisposition.REOPEN,
            ConfirmationDisposition.EXTEND,
        }


@dataclass(frozen=True)
class Capabilities:
    """Facts observed from the active harness, never inferred from this package."""

    request_user_input_exposed: bool
    mode_allows_request_user_input: bool

    @property
    def surface(self) -> Surface:
        if self.request_user_input_exposed and self.mode_allows_request_user_input:
            return Surface.NATIVE
        return Surface.FALLBACK

    @property
    def fallback_reason(self) -> str | None:
        if not self.request_user_input_exposed:
            return "request_user_input is not exposed by the active harness"
        if not self.mode_allows_request_user_input:
            return "the active collaboration mode does not permit request_user_input"
        return None


def plan_chunks(snapshot: RoundSnapshot) -> tuple[tuple[Question, ...], ...]:
    """Chunk one already-captured frontier without recomputing it."""

    return snapshot.chunks(CODEX_MAX_QUESTIONS)


def _native_option(option: Option, recommended: bool) -> dict[str, str]:
    label = option.label
    if recommended and not label.endswith("(Recommended)"):
        label = f"{label} (Recommended)"
    return {"label": label, "description": option.description}


def serialize_native(questions: Sequence[Question]) -> dict[str, list[dict[str, object]]]:
    """Build one request_user_input payload from at most three questions."""

    if not 1 <= len(questions) <= CODEX_MAX_QUESTIONS:
        raise ValueError("Codex native chunks must contain one to three questions")
    payload: list[dict[str, object]] = []
    for question in questions:
        if len(question.header) > 12:
            raise ValueError(f"Codex header for {question.id!r} exceeds 12 characters")
        if (
            MULTIPLE_SENTENCES.search(question.prompt.strip())
            or len(question.prompt) > CODEX_MAX_PROMPT_CHARS
        ):
            raise ValueError(
                f"Codex prompt for {question.id!r} must be one short sentence"
            )
        if not 2 <= len(question.options) <= CODEX_MAX_OPTIONS:
            raise ValueError(f"Codex question {question.id!r} needs two or three options")
        if any(not 1 <= len(option.label.split()) <= 5 for option in question.options):
            raise ValueError(f"Codex option labels for {question.id!r} need one to five words")
        if any(
            MULTIPLE_SENTENCES.search(option.description.strip())
            or len(option.description) > CODEX_MAX_DESCRIPTION_CHARS
            for option in question.options
        ):
            raise ValueError(
                f"Codex option descriptions for {question.id!r} must be one short sentence"
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
                f"Codex option labels for {question.id!r} exceed five words "
                "after recommendation marking"
            )
        payload.append(
            {
                "id": question.id,
                "header": question.header,
                "question": question.prompt,
                "options": native_options,
            }
        )
    return {"questions": payload}


def normalize_native_response(
    questions: Sequence[Question], response: Mapping[str, object]
) -> dict[str, str]:
    """Normalize the request_user_input response envelope into canonical strings."""

    raw_answers = response.get("answers")
    if not isinstance(raw_answers, Mapping):
        raise ValueError("native response must contain an answers mapping")
    expected = {question.id for question in questions}
    if set(raw_answers) != expected:
        raise ValueError("native response ids do not match the submitted chunk")

    normalized: dict[str, str] = {}
    for question in questions:
        entry = raw_answers[question.id]
        if isinstance(entry, Mapping):
            entry = entry.get("answers")
        if isinstance(entry, list):
            if not entry or any(
                not isinstance(value, str) or not value.strip() for value in entry
            ):
                raise ValueError(
                    f"native answer for {question.id!r} must contain non-empty strings"
                )
            values = [value.strip() for value in entry]
            sentinel = values[0].casefold()
            if sentinel in {"none of the above", "other"} and len(values) > 1:
                entry = " ".join(values[1:])
            else:
                entry = " — ".join(values)
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"native answer for {question.id!r} must be a non-empty string")
        normalized[question.id] = entry.strip()
    return normalized


def render_fallback(questions: Sequence[Question], reason: str) -> str:
    """Render an explicit, truthful fallback when the native surface is absent."""

    lines = [f"Native questionnaire unavailable: {reason}.", ""]
    for index, question in enumerate(questions, start=1):
        lines.append(f"{index}. {question.header}: {question.prompt}")
        for option_index, option in enumerate(question.options):
            marker = " (Recommended)" if option_index == question.recommended else ""
            lines.append(f"   - {option.label}{marker}: {option.description}")
        lines.append("   - Other: provide a custom answer.")
    lines.append("")
    lines.append("Reply with one answer for every numbered question.")
    return "\n".join(lines)


def confirmation_question() -> Question:
    return Question(
        id="shared_understanding",
        header="Confirm",
        prompt="Have we reached a complete shared understanding?",
        options=(
            Option("Confirmed", "The design tree is complete; stop interviewing."),
            Option("Reopen", "Add the missing concern to the design tree and continue."),
        ),
        recommended=0,
    )


def resolve_confirmation(value: str) -> ConfirmationResult:
    """Gate action on one explicit confirmation; every other answer continues."""

    answer = value.strip()
    if not answer:
        raise ValueError("confirmation answer must be non-empty")
    canonical = answer.removesuffix(" (Recommended)").removesuffix(" (recommended)")
    if canonical == "Confirmed":
        return ConfirmationResult(ConfirmationDisposition.CONFIRMED)
    if canonical == "Reopen":
        return ConfirmationResult(ConfirmationDisposition.REOPEN)
    return ConfirmationResult(ConfirmationDisposition.EXTEND, concern=answer)
