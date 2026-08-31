"""Codex/T3 serialization for the canonical grilling contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from .grilling import Option, Question, RoundSnapshot


CODEX_MAX_QUESTIONS = 3
CODEX_MAX_OPTIONS = 3


class Surface(str, Enum):
    NATIVE = "request_user_input"
    FALLBACK = "text-fallback"


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
        if not 2 <= len(question.options) <= CODEX_MAX_OPTIONS:
            raise ValueError(f"Codex question {question.id!r} needs two or three options")
        if any(not 1 <= len(option.label.split()) <= 5 for option in question.options):
            raise ValueError(f"Codex option labels for {question.id!r} need one to five words")
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
                f"Codex option labels for {question.id!r} exceed five words after recommendation marking"
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
            if len(entry) != 1:
                raise ValueError(
                    f"native answer for {question.id!r} must contain exactly one value"
                )
            entry = entry[0]
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
            marker = " (recommended)" if option_index == question.recommended else ""
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
