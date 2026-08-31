"""Canonical design-tree and frontier-round contract.

The types in this module are harness-neutral.  Harness adapters serialize an
immutable ``RoundSnapshot`` and return normalized answers.  Only a complete
snapshot may be committed, which prevents adapter question limits from
changing the dependency frontier mid-round.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class Option:
    """One user-owned choice and its concise trade-off."""

    label: str
    description: str

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("option label must be non-empty")
        if not self.description.strip():
            raise ValueError("option description must be non-empty")


@dataclass(frozen=True)
class Decision:
    """A design-tree node whose prerequisites determine frontier membership."""

    id: str
    header: str
    prompt: str
    options: tuple[Option, ...]
    recommended: int = 0
    depends_on: frozenset[str] = field(default_factory=frozenset)
    facts_required: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", self.id):
            raise ValueError("decision id must be lowercase snake_case")
        if not self.header.strip() or not self.prompt.strip():
            raise ValueError("decision header and prompt must be non-empty")
        if len(self.options) < 2:
            raise ValueError("a decision needs at least two options")
        if not 0 <= self.recommended < len(self.options):
            raise ValueError("recommended option index is out of range")
        if self.id in self.depends_on:
            raise ValueError("a decision cannot depend on itself")


@dataclass(frozen=True)
class Question:
    """A decision projected into the canonical questionnaire shape."""

    id: str
    header: str
    prompt: str
    options: tuple[Option, ...]
    recommended: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", self.id):
            raise ValueError("question id must be lowercase snake_case")
        if not self.header.strip() or not self.prompt.strip():
            raise ValueError("question header and prompt must be non-empty")
        if len(self.options) < 2 or not 0 <= self.recommended < len(self.options):
            raise ValueError("question choices and recommendation are invalid")

    @classmethod
    def from_decision(cls, decision: Decision) -> "Question":
        return cls(
            id=decision.id,
            header=decision.header,
            prompt=decision.prompt,
            options=decision.options,
            recommended=decision.recommended,
        )


@dataclass(frozen=True)
class Answer:
    """A normalized native or free-form answer."""

    question_id: str
    value: str
    custom: bool


@dataclass(frozen=True)
class RoundSnapshot:
    """The complete immutable frontier captured before any adapter calls."""

    questions: tuple[Question, ...]

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(question.id for question in self.questions)

    def chunks(self, maximum: int) -> tuple[tuple[Question, ...], ...]:
        if maximum < 1:
            raise ValueError("maximum chunk size must be positive")
        return tuple(
            self.questions[index : index + maximum]
            for index in range(0, len(self.questions), maximum)
        )


@dataclass(frozen=True)
class InterviewState:
    """Settled decisions and facts at a frontier boundary."""

    answers: Mapping[str, Answer] = field(default_factory=dict)
    facts: frozenset[str] = field(default_factory=frozenset)

    def with_facts(self, facts: Iterable[str]) -> "InterviewState":
        return replace(self, facts=self.facts | frozenset(facts))


class DesignTree:
    """Validate and traverse one deterministic design tree."""

    def __init__(self, decisions: Sequence[Decision]) -> None:
        self._decisions = tuple(decisions)
        self._by_id = {decision.id: decision for decision in self._decisions}
        if len(self._by_id) != len(self._decisions):
            raise ValueError("decision ids must be unique")
        known = set(self._by_id)
        for decision in self._decisions:
            unknown = decision.depends_on - known
            if unknown:
                raise ValueError(
                    f"decision {decision.id!r} has unknown dependencies: {sorted(unknown)}"
                )
        self._reject_cycles()

    def _reject_cycles(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(decision_id: str) -> None:
            if decision_id in visiting:
                raise ValueError("design tree contains a dependency cycle")
            if decision_id in visited:
                return
            visiting.add(decision_id)
            for dependency in self._by_id[decision_id].depends_on:
                visit(dependency)
            visiting.remove(decision_id)
            visited.add(decision_id)

        for decision_id in self._by_id:
            visit(decision_id)

    def frontier(self, state: InterviewState) -> tuple[Decision, ...]:
        settled = set(state.answers)
        return tuple(
            decision
            for decision in self._decisions
            if decision.id not in settled
            and decision.depends_on <= settled
            and decision.facts_required <= state.facts
        )

    def snapshot(self, state: InterviewState) -> RoundSnapshot:
        return RoundSnapshot(
            tuple(Question.from_decision(decision) for decision in self.frontier(state))
        )

    def complete(self, state: InterviewState) -> bool:
        """Return true only when every known decision is settled."""

        return set(state.answers) >= set(self._by_id)

    def blocked_on_facts(self, state: InterviewState) -> tuple[Decision, ...]:
        """Expose decisions that must wait for discoverable evidence, not the user."""

        settled = set(state.answers)
        return tuple(
            decision
            for decision in self._decisions
            if decision.id not in settled
            and decision.depends_on <= settled
            and not decision.facts_required <= state.facts
        )

    def commit_snapshot(
        self,
        state: InterviewState,
        snapshot: RoundSnapshot,
        raw_answers: Mapping[str, str],
    ) -> InterviewState:
        """Commit one whole frontier or reject the partial adapter result."""

        expected = set(snapshot.ids)
        received = set(raw_answers)
        if received != expected:
            missing = sorted(expected - received)
            unexpected = sorted(received - expected)
            raise ValueError(
                f"snapshot answers must be complete; missing={missing}, unexpected={unexpected}"
            )

        answers = dict(state.answers)
        for question in snapshot.questions:
            value = str(raw_answers[question.id]).strip()
            if not value:
                raise ValueError(f"answer for {question.id!r} must be non-empty")
            known_labels = {option.label for option in question.options}
            canonical_value = value.removesuffix(" (Recommended)")
            answers[question.id] = Answer(
                question_id=question.id,
                value=canonical_value if canonical_value in known_labels else value,
                custom=canonical_value not in known_labels,
            )
        return replace(state, answers=answers)
