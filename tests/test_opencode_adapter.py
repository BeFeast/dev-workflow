from __future__ import annotations

import subprocess
import unittest

from dev_workflow.grilling import (
    Decision,
    DesignTree,
    InterviewState,
    Option,
    Question,
)
from dev_workflow.opencode import (
    Capabilities,
    ConfirmationDisposition,
    QuestionPermission,
    Surface,
    confirmation_question,
    normalize_model_output,
    plan_calls,
    probe_capabilities,
    render_fallback,
    resolve_confirmation,
    serialize_native,
)


def decision(
    decision_id: str, *, depends_on: frozenset[str] = frozenset()
) -> Decision:
    return Decision(
        id=decision_id,
        header=decision_id.replace("_", " ").title(),
        prompt=f"Choose the {decision_id} direction",
        options=(
            Option("Fast path", "Prefer delivery speed over later flexibility."),
            Option("Durable path", "Prefer future flexibility over immediate speed."),
        ),
        recommended=1,
        depends_on=depends_on,
    )


def completed(version: str = "1.18.25") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["opencode", "--version"], returncode=0, stdout=f"{version}\n", stderr=""
    )


def model_output(questions: tuple[Question, ...], answers: list[list[str]]) -> str:
    """Reproduce OpenCode 1.18.25 question.ts lines 30-39."""

    formatted = ", ".join(
        f'"{question.prompt}"="{", ".join(answer) if answer else "Unanswered"}"'
        for question, answer in zip(questions, answers, strict=True)
    )
    return (
        f"User has answered your questions: {formatted}. "
        "You can now continue with the user's answers in mind."
    )


class OpenCodeAdapterTests(unittest.TestCase):
    def test_probe_records_version_and_observed_surface(self) -> None:
        capabilities = probe_capabilities(
            question_exposed=True,
            question_transport_available=True,
            question_permission=QuestionPermission.ASK,
            invocation="run",
            runner=lambda _argv: completed(),
        )
        self.assertEqual(capabilities.version, "1.18.25")
        self.assertEqual(capabilities.surface, Surface.NATIVE)
        self.assertEqual(capabilities.invocation, "run")
        self.assertIsNone(capabilities.version_probe_error)

        tui = probe_capabilities(
            question_exposed=True,
            question_transport_available=True,
            question_permission=QuestionPermission.ALLOW,
            invocation="tui",
            runner=lambda _argv: completed(),
        )
        self.assertEqual(tui.surface, Surface.NATIVE)

    def test_capability_verdict_uses_surface_not_command_or_version_guess(self) -> None:
        denied = Capabilities(
            version="1.18.25",
            question_exposed=True,
            question_transport_available=True,
            question_permission=QuestionPermission.DENY,
            invocation="tui",
        )
        self.assertEqual(denied.surface, Surface.FALLBACK)
        self.assertIn("denies", denied.fallback_reason or "")

        detached = Capabilities(
            version="99.0.0",
            question_exposed=True,
            question_transport_available=False,
            invocation="run",
        )
        self.assertEqual(detached.surface, Surface.FALLBACK)
        self.assertIn("transport", detached.fallback_reason or "")

        absent = Capabilities(
            version=None,
            question_exposed=False,
            question_transport_available=True,
            version_probe_error="binary unavailable",
        )
        self.assertEqual(absent.surface, Surface.FALLBACK)
        self.assertIn("not exposed", absent.fallback_reason or "")

    def test_version_probe_failure_is_evidence_not_a_false_tool_verdict(self) -> None:
        def unavailable(_argv: object) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("opencode")

        capabilities = probe_capabilities(
            question_exposed=True,
            question_transport_available=True,
            runner=unavailable,
        )
        self.assertIsNone(capabilities.version)
        self.assertIn("opencode", capabilities.version_probe_error or "")
        self.assertEqual(capabilities.surface, Surface.NATIVE)

    def test_complete_frontier_is_one_immutable_ordered_call(self) -> None:
        tree = DesignTree(
            [
                decision("first"),
                decision("second"),
                decision("child", depends_on=frozenset({"first"})),
            ]
        )
        state = InterviewState()
        snapshot = tree.snapshot(state)
        self.assertEqual(snapshot.ids, ("first", "second"))
        calls = plan_calls(snapshot)
        self.assertEqual(len(calls), 1)
        self.assertEqual(tuple(item.id for item in calls[0]), snapshot.ids)

        with self.assertRaisesRegex(ValueError, "must be complete"):
            tree.commit_snapshot(state, snapshot, {"first": "Durable path"})
        self.assertNotIn("child", tree.snapshot(state).ids)

    def test_native_payload_uses_exact_question_schema_and_multiple(self) -> None:
        snapshot = DesignTree(
            [decision("delivery"), decision("signals")]
        ).snapshot(InterviewState())
        payload = serialize_native(
            snapshot.questions,
            multiple_question_ids=frozenset({"signals"}),
        )
        self.assertEqual(set(payload), {"questions"})
        self.assertEqual(len(payload["questions"]), 2)
        first, second = payload["questions"]
        self.assertEqual(
            set(first), {"question", "header", "options", "multiple"}
        )
        self.assertNotIn("id", first)
        self.assertNotIn("custom", first)
        self.assertFalse(first["multiple"])
        self.assertTrue(second["multiple"])
        self.assertEqual(
            first["options"][0]["label"], "Durable path (Recommended)"
        )
        self.assertEqual(first["options"][1]["label"], "Fast path")
        self.assertNotIn("Other", [item["label"] for item in first["options"]])

    def test_ordered_answers_map_by_position_and_preserve_multiple_order(self) -> None:
        tree = DesignTree([decision("delivery"), decision("signals")])
        snapshot = tree.snapshot(InterviewState())
        normalized = normalize_model_output(
            snapshot.questions,
            model_output(
                snapshot.questions,
                [
                    ["Durable path (Recommended)"],
                    ["Fast path", "Durable path (Recommended)"],
                ],
            ),
        )
        self.assertEqual(
            normalized,
            {
                "delivery": "Durable path (Recommended)",
                "signals": "Fast path, Durable path (Recommended)",
            },
        )
        state = tree.commit_snapshot(InterviewState(), snapshot, normalized)
        self.assertEqual(state.answers["delivery"].value, "Durable path")
        self.assertFalse(state.answers["delivery"].custom)
        self.assertEqual(
            state.answers["signals"].value,
            "Fast path, Durable path (Recommended)",
        )
        self.assertTrue(state.answers["signals"].custom)

    def test_custom_answer_is_preserved_without_an_other_sentinel(self) -> None:
        tree = DesignTree([decision("delivery")])
        snapshot = tree.snapshot(InterviewState())
        normalized = normalize_model_output(
            snapshot.questions,
            model_output(
                snapshot.questions,
                [["Keep both linked skills, retaining attribution"]],
            ),
        )
        self.assertEqual(
            normalized["delivery"],
            "Keep both linked skills, retaining attribution",
        )
        state = tree.commit_snapshot(InterviewState(), snapshot, normalized)
        self.assertTrue(state.answers["delivery"].custom)

    def test_model_gets_formatted_output_not_private_answers_metadata(self) -> None:
        questions = DesignTree(
            [decision("delivery"), decision("signals")]
        ).snapshot(InterviewState()).questions
        # This is the old false interface. OpenCode stores it in metadata but
        # message-v2 projects only the formatted tool output to the model.
        with self.assertRaisesRegex(ValueError, "metadata is not exposed"):
            normalize_model_output(
                questions,  # type: ignore[arg-type]
                {"answers": [["Fast path"], ["Durable path"]]},  # type: ignore[arg-type]
            )

        actual = model_output(
            questions,
            [["Durable path (Recommended)"], ["Fast path", "custom signal"]],
        )
        self.assertEqual(
            normalize_model_output(questions, actual),
            {
                "delivery": "Durable path (Recommended)",
                "signals": "Fast path, custom signal",
            },
        )

    def test_malformed_or_unanswered_model_output_is_rejected(self) -> None:
        questions = DesignTree(
            [decision("delivery"), decision("signals")]
        ).snapshot(InterviewState()).questions
        with self.assertRaisesRegex(ValueError, "ordered successor"):
            normalize_model_output(
                questions,
                model_output((questions[0],), [["Fast path"]]),
            )
        with self.assertRaisesRegex(ValueError, "unanswered"):
            normalize_model_output(
                questions,
                model_output(questions, [[], ["Fast path"]]),
            )

    def test_unavailable_tool_fallback_is_truthful(self) -> None:
        questions = DesignTree(
            [decision("delivery"), decision("signals")]
        ).snapshot(InterviewState()).questions
        output = render_fallback(
            questions,
            "the active OpenCode client has no question response transport",
            multiple_question_ids=frozenset({"signals"}),
        )
        self.assertIn("Native questionnaire unavailable:", output)
        self.assertIn("no question response transport", output)
        self.assertIn("select all that apply", output)
        self.assertIn("Custom answer", output)
        self.assertIn("Durable path (Recommended)", output)

    def test_final_confirmation_uses_question_and_only_explicit_yes_acts(self) -> None:
        question = confirmation_question()
        payload = serialize_native((question,))
        native = payload["questions"][0]
        self.assertFalse(native["multiple"])
        self.assertEqual(native["header"], "Confirm")
        self.assertEqual(native["options"][0]["label"], "Confirmed (Recommended)")

        normalized = normalize_model_output(
            (question,), model_output((question,), [["Confirmed (Recommended)"]])
        )
        confirmed = resolve_confirmation(normalized["shared_understanding"])
        self.assertEqual(confirmed.disposition, ConfirmationDisposition.CONFIRMED)
        self.assertTrue(confirmed.may_act)

        reopened = resolve_confirmation("Reopen")
        self.assertEqual(reopened.disposition, ConfirmationDisposition.REOPEN)
        self.assertTrue(reopened.continue_interview)

        custom = resolve_confirmation("We still need an offline decision")
        self.assertEqual(custom.disposition, ConfirmationDisposition.EXTEND)
        self.assertEqual(custom.concern, "We still need an offline decision")
        self.assertFalse(custom.may_act)


if __name__ == "__main__":
    unittest.main()
