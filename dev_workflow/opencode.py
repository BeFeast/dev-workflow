"""OpenCode serialization for the canonical grilling contract.

OpenCode's ``question`` tool has no stable question id in its payload or
response.  This adapter therefore binds answers to one immutable frontier by
position and rejects any incomplete or reordered response shape before the
shared design tree can commit it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import subprocess
from typing import Callable, Mapping, Sequence

from .grilling import Option, Question, RoundSnapshot


OPENCODE_MAX_HEADER_CHARS = 30
OPENCODE_MAX_OPTION_WORDS = 5
VERSION = re.compile(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)")


class Surface(str, Enum):
    NATIVE = "question"
    FALLBACK = "text-fallback"


class QuestionPermission(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    UNKNOWN = "unknown"


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
    """Observed facts about one active OpenCode session.

    ``invocation`` is diagnostic evidence only.  In particular, ``run`` is not
    a denial signal: current OpenCode versions can attach a question UI to that
    command, and future versions may expose other interactive transports.
    """

    version: str | None
    question_exposed: bool
    question_transport_available: bool
    question_permission: QuestionPermission = QuestionPermission.UNKNOWN
    invocation: str | None = None
    version_probe_error: str | None = None

    @property
    def surface(self) -> Surface:
        if (
            self.question_exposed
            and self.question_transport_available
            and self.question_permission is not QuestionPermission.DENY
        ):
            return Surface.NATIVE
        return Surface.FALLBACK

    @property
    def fallback_reason(self) -> str | None:
        if not self.question_exposed:
            return "question is not exposed by the active OpenCode session"
        if self.question_permission is QuestionPermission.DENY:
            return "the active OpenCode permission policy denies question"
        if not self.question_transport_available:
            return "the active OpenCode client has no question response transport"
        return None


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )


def probe_capabilities(
    *,
    question_exposed: bool,
    question_transport_available: bool,
    question_permission: QuestionPermission = QuestionPermission.UNKNOWN,
    invocation: str | None = None,
    runner: Runner = _default_runner,
) -> Capabilities:
    """Probe the installed version and combine it with active-session facts.

    Tool exposure and response transport must come from the active OpenCode
    session; a local version number cannot prove either one.  Keeping those
    observations explicit prevents command names or version thresholds from
    becoming false capability assumptions.
    """

    try:
        result = runner(("opencode", "--version"))
    except (OSError, subprocess.SubprocessError) as error:
        return Capabilities(
            version=None,
            question_exposed=question_exposed,
            question_transport_available=question_transport_available,
            question_permission=question_permission,
            invocation=invocation,
            version_probe_error=str(error),
        )

    output = "\n".join((result.stdout or "", result.stderr or "")).strip()
    match = VERSION.search(output)
    error = None
    if result.returncode != 0:
        error = output or f"opencode --version exited {result.returncode}"
    elif match is None:
        error = "opencode --version did not return a semantic version"
    return Capabilities(
        version=match.group(1) if match and result.returncode == 0 else None,
        question_exposed=question_exposed,
        question_transport_available=question_transport_available,
        question_permission=question_permission,
        invocation=invocation,
        version_probe_error=error,
    )


def plan_calls(snapshot: RoundSnapshot) -> tuple[tuple[Question, ...], ...]:
    """Keep the full snapshotted frontier in one ordered OpenCode call."""

    return (snapshot.questions,) if snapshot.questions else ()


def _native_option(option: Option, recommended: bool) -> dict[str, str]:
    label = option.label
    if recommended and not label.endswith("(Recommended)"):
        label = f"{label} (Recommended)"
    return {"label": label, "description": option.description}


def serialize_native(
    questions: Sequence[Question],
    *,
    multiple_question_ids: frozenset[str] = frozenset(),
) -> dict[str, list[dict[str, object]]]:
    """Build the exact ordered ``question`` tool input."""

    if not questions:
        raise ValueError("OpenCode native calls need at least one question")
    question_ids = {question.id for question in questions}
    unknown_multiple = multiple_question_ids - question_ids
    if unknown_multiple:
        raise ValueError(
            f"multiple question ids are not in this call: {sorted(unknown_multiple)}"
        )

    payload: list[dict[str, object]] = []
    for question in questions:
        if len(question.header) > OPENCODE_MAX_HEADER_CHARS:
            raise ValueError(
                f"OpenCode header for {question.id!r} exceeds 30 characters"
            )
        ordered = (
            question.options[question.recommended],
            *(
                option
                for index, option in enumerate(question.options)
                if index != question.recommended
            ),
        )
        options = [
            _native_option(option, index == 0)
            for index, option in enumerate(ordered)
        ]
        if any(
            not 1 <= len(option["label"].split()) <= OPENCODE_MAX_OPTION_WORDS
            for option in options
        ):
            raise ValueError(
                f"OpenCode option labels for {question.id!r} need one to five words"
            )
        payload.append(
            {
                "question": question.prompt,
                "header": question.header,
                "options": options,
                "multiple": question.id in multiple_question_ids,
            }
        )
    return {"questions": payload}


def normalize_native_response(
    questions: Sequence[Question],
    response: Mapping[str, object],
    *,
    multiple_question_ids: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Map OpenCode's ordered ``string[][]`` answers to stable question ids."""

    raw_answers = response.get("answers")
    if not isinstance(raw_answers, (list, tuple)):
        raise ValueError("native response must contain an ordered answers array")
    if len(raw_answers) != len(questions):
        raise ValueError("native answer count does not match the submitted questions")

    question_ids = {question.id for question in questions}
    unknown_multiple = multiple_question_ids - question_ids
    if unknown_multiple:
        raise ValueError(
            f"multiple question ids are not in this response: {sorted(unknown_multiple)}"
        )

    normalized: dict[str, str] = {}
    for question, raw in zip(questions, raw_answers, strict=True):
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValueError(
                f"native answer for {question.id!r} must be a non-empty string array"
            )
        if question.id not in multiple_question_ids and len(raw) != 1:
            raise ValueError(
                f"single-select answer for {question.id!r} must contain one value"
            )
        if any(not isinstance(value, str) or not value.strip() for value in raw):
            raise ValueError(
                f"native answer for {question.id!r} must contain non-empty strings"
            )
        values = [value.strip() for value in raw]
        normalized[question.id] = " — ".join(values)
    return normalized


def render_fallback(
    questions: Sequence[Question],
    reason: str,
    *,
    multiple_question_ids: frozenset[str] = frozenset(),
) -> str:
    """Render a truthful fallback without claiming native interaction."""

    lines = [f"Native questionnaire unavailable: {reason}.", ""]
    for index, question in enumerate(questions, start=1):
        suffix = " (select all that apply)" if question.id in multiple_question_ids else ""
        lines.append(f"{index}. {question.header}: {question.prompt}{suffix}")
        for option_index, option in enumerate(question.options):
            marker = " (Recommended)" if option_index == question.recommended else ""
            lines.append(f"   - {option.label}{marker}: {option.description}")
        lines.append("   - Custom answer: type your own response.")
    lines.extend(("", "Reply with one answer for every numbered question."))
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
    """Gate action on explicit confirmation through the active surface."""

    answer = value.strip()
    if not answer:
        raise ValueError("confirmation answer must be non-empty")
    canonical = answer.removesuffix(" (Recommended)").removesuffix(" (recommended)")
    if canonical == "Confirmed":
        return ConfirmationResult(ConfirmationDisposition.CONFIRMED)
    if canonical == "Reopen":
        return ConfirmationResult(ConfirmationDisposition.REOPEN)
    return ConfirmationResult(ConfirmationDisposition.EXTEND, concern=answer)
