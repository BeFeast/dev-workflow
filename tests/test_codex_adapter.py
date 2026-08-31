from __future__ import annotations

from dataclasses import replace
import unittest

from dev_workflow.codex import (
    Capabilities,
    ConfirmationDisposition,
    Surface,
    confirmation_question,
    normalize_native_response,
    plan_chunks,
    render_fallback,
    resolve_confirmation,
    serialize_native,
)
from dev_workflow.grilling import Decision, DesignTree, InterviewState, Option


def root(decision_id: str, *, depends_on: frozenset[str] = frozenset()) -> Decision:
    return Decision(
        id=decision_id,
        header=decision_id[:12],
        prompt=f"Choose the {decision_id} direction",
        options=(
            Option("Speed first", "Choose delivery speed as the priority."),
            Option("Durability first", "Choose future flexibility as the priority."),
        ),
        recommended=1,
        depends_on=depends_on,
    )


class CodexAdapterTests(unittest.TestCase):
    def test_native_surface_requires_tool_and_permitted_mode(self) -> None:
        self.assertEqual(Capabilities(True, True).surface, Surface.NATIVE)
        denied = Capabilities(True, False)
        self.assertEqual(denied.surface, Surface.FALLBACK)
        self.assertIn("mode", denied.fallback_reason or "")
        absent = Capabilities(False, True)
        self.assertEqual(absent.surface, Surface.FALLBACK)
        self.assertIn("not exposed", absent.fallback_reason or "")

    def test_larger_frontier_is_snapshotted_before_three_question_chunks(self) -> None:
        tree = DesignTree(
            [
                *(root(f"root_{index}") for index in range(1, 6)),
                root("child", depends_on=frozenset({"root_1"})),
            ]
        )
        initial = InterviewState()
        snapshot = tree.snapshot(initial)
        self.assertEqual(
            snapshot.ids, ("root_1", "root_2", "root_3", "root_4", "root_5")
        )
        chunks = plan_chunks(snapshot)
        self.assertEqual(tuple(len(chunk) for chunk in chunks), (3, 2))
        self.assertEqual(
            tuple(item["id"] for item in serialize_native(chunks[0])["questions"]),
            ("root_1", "root_2", "root_3"),
        )

        with self.assertRaisesRegex(ValueError, "must be complete"):
            tree.commit_snapshot(
                initial,
                snapshot,
                {
                    question.id: "Durability first (Recommended)"
                    for question in chunks[0]
                },
            )
        self.assertNotIn("child", tree.snapshot(initial).ids)

        collected = {
            question.id: "Durability first (Recommended)"
            for chunk in chunks
            for question in chunk
        }
        settled = tree.commit_snapshot(initial, snapshot, collected)
        self.assertEqual(tree.snapshot(settled).ids, ("child",))

    def test_native_payload_reorders_recommendation_and_uses_exact_schema(self) -> None:
        tree = DesignTree([root("delivery")])
        question = tree.snapshot(InterviewState()).questions[0]
        payload = serialize_native((question,))
        self.assertEqual(set(payload), {"questions"})
        native = payload["questions"][0]
        self.assertEqual(
            set(native), {"id", "header", "question", "options"}
        )
        self.assertEqual(
            native["options"][0]["label"], "Durability first (Recommended)"
        )
        self.assertEqual(native["options"][1]["label"], "Speed first")
        self.assertNotIn("Other", [option["label"] for option in native["options"]])

    def test_native_response_normalizes_recommended_and_other_values(self) -> None:
        tree = DesignTree([root("delivery"), root("scope")])
        questions = tree.snapshot(InterviewState()).questions
        normalized = normalize_native_response(
            questions,
            {
                "answers": {
                    "delivery": {
                        "answers": ["Durability first (Recommended)"]
                    },
                    "scope": {"answers": ["Keep both linked skills"]},
                }
            },
        )
        state = tree.commit_snapshot(
            InterviewState(), tree.snapshot(InterviewState()), normalized
        )
        self.assertEqual(state.answers["delivery"].value, "Durability first")
        self.assertFalse(state.answers["delivery"].custom)
        self.assertEqual(state.answers["scope"].value, "Keep both linked skills")
        self.assertTrue(state.answers["scope"].custom)

    def test_unavailable_tool_fallback_is_explicit_and_supports_other(self) -> None:
        tree = DesignTree([root("delivery")])
        snapshot = tree.snapshot(InterviewState())
        output = render_fallback(snapshot.questions, "request_user_input is not exposed")
        self.assertIn("Native questionnaire unavailable:", output)
        self.assertIn("request_user_input is not exposed", output)
        self.assertIn("Other: provide a custom answer", output)
        self.assertIn("Durability first (Recommended)", output)
        state = tree.commit_snapshot(
            InterviewState(),
            snapshot,
            {"delivery": "Durability first (Recommended)"},
        )
        self.assertEqual(state.answers["delivery"].value, "Durability first")
        self.assertFalse(state.answers["delivery"].custom)

    def test_native_schema_rejects_multi_sentence_prompt_or_description(self) -> None:
        question = DesignTree([root("delivery")]).snapshot(InterviewState()).questions[0]
        with self.assertRaisesRegex(ValueError, "prompt.*one short sentence"):
            serialize_native(
                (
                    replace(question, prompt="Choose a direction. Then explain it."),
                )
            )
        options = (
            Option("Speed first", "Choose speed. Accept less flexibility."),
            question.options[1],
        )
        with self.assertRaisesRegex(ValueError, "descriptions.*one short sentence"):
            serialize_native((replace(question, options=options),))

    def test_final_confirmation_uses_native_questionnaire_shape(self) -> None:
        payload = serialize_native((confirmation_question(),))
        question = payload["questions"][0]
        self.assertEqual(question["id"], "shared_understanding")
        self.assertEqual(question["header"], "Confirm")
        self.assertEqual(question["options"][0]["label"], "Confirmed (Recommended)")
        self.assertEqual(question["options"][1]["label"], "Reopen")

    def test_only_explicit_confirmation_allows_action(self) -> None:
        question = confirmation_question()
        normalized = normalize_native_response(
            (question,),
            {
                "answers": {
                    "shared_understanding": {
                        "answers": ["Confirmed (Recommended)"]
                    }
                }
            },
        )
        confirmed = resolve_confirmation(normalized["shared_understanding"])
        self.assertEqual(
            confirmed.disposition, ConfirmationDisposition.CONFIRMED
        )
        self.assertTrue(confirmed.may_act)
        self.assertFalse(confirmed.continue_interview)
        self.assertFalse(confirmed.extends_tree)

        reopened = resolve_confirmation("Reopen")
        self.assertEqual(reopened.disposition, ConfirmationDisposition.REOPEN)
        self.assertFalse(reopened.may_act)
        self.assertTrue(reopened.continue_interview)
        self.assertTrue(reopened.extends_tree)

        custom = resolve_confirmation("We still need an offline decision")
        self.assertEqual(custom.disposition, ConfirmationDisposition.EXTEND)
        self.assertEqual(custom.concern, "We still need an offline decision")
        self.assertFalse(custom.may_act)
        self.assertTrue(custom.continue_interview)
        self.assertTrue(custom.extends_tree)


if __name__ == "__main__":
    unittest.main()
