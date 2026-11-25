from __future__ import annotations

from dataclasses import replace
import unittest

from dev_workflow.claude import (
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
        prompt=f"Which {decision_id} direction should we take?",
        options=(
            Option("Speed first", "Choose delivery speed as the priority."),
            Option("Durability first", "Choose future flexibility as the priority."),
        ),
        recommended=1,
        depends_on=depends_on,
    )


class ClaudeAdapterTests(unittest.TestCase):
    def test_native_surface_requires_exposed_and_permitted_tool(self) -> None:
        self.assertEqual(Capabilities(True, True).surface, Surface.NATIVE)
        denied = Capabilities(True, False)
        self.assertEqual(denied.surface, Surface.FALLBACK)
        self.assertIn("denied", denied.fallback_reason or "")
        absent = Capabilities(False, True)
        self.assertEqual(absent.surface, Surface.FALLBACK)
        self.assertIn("not exposed", absent.fallback_reason or "")

    def test_frontier_is_snapshotted_before_four_question_chunks(self) -> None:
        tree = DesignTree(
            [
                *(root(f"root_{index}") for index in range(1, 7)),
                root("child", depends_on=frozenset({"root_1"})),
            ]
        )
        initial = InterviewState()
        snapshot = tree.snapshot(initial)
        self.assertEqual(
            snapshot.ids,
            ("root_1", "root_2", "root_3", "root_4", "root_5", "root_6"),
        )
        chunks = plan_chunks(snapshot)
        self.assertEqual(tuple(len(chunk) for chunk in chunks), (4, 2))
        self.assertEqual(len(serialize_native(chunks[0])["questions"]), 4)

        with self.assertRaisesRegex(ValueError, "must be complete"):
            tree.commit_snapshot(
                initial,
                snapshot,
                {question.id: "Durability first (Recommended)" for question in chunks[0]},
            )
        self.assertNotIn("child", tree.snapshot(initial).ids)

        collected = {
            question.id: "Durability first (Recommended)"
            for chunk in chunks
            for question in chunk
        }
        settled = tree.commit_snapshot(initial, snapshot, collected)
        self.assertEqual(tree.snapshot(settled).ids, ("child",))

    def test_payload_uses_exact_schema_and_single_select_default(self) -> None:
        question = DesignTree([root("delivery")]).snapshot(InterviewState()).questions[0]
        payload = serialize_native((question,))
        self.assertEqual(set(payload), {"questions"})
        native = payload["questions"][0]
        self.assertEqual(
            set(native), {"question", "header", "options", "multiSelect"}
        )
        self.assertFalse(native["multiSelect"])
        self.assertEqual(native["options"][0]["label"], "Durability first (Recommended)")
        self.assertEqual(native["options"][1]["label"], "Speed first")
        self.assertNotIn("id", native)

    def test_multi_select_payload_and_comma_separated_answer_are_preserved(self) -> None:
        question = DesignTree([root("features")]).snapshot(InterviewState()).questions[0]
        payload = serialize_native((question,), multi_select_ids={"features"})
        self.assertTrue(payload["questions"][0]["multiSelect"])
        normalized = normalize_native_response(
            (question,),
            {"answers": {question.prompt: "Speed first, Durability first"}},
        )
        self.assertEqual(normalized["features"], "Speed first, Durability first")

    def test_single_select_answer_normalizes_to_known_option(self) -> None:
        tree = DesignTree([root("delivery")])
        snapshot = tree.snapshot(InterviewState())
        question = snapshot.questions[0]
        normalized = normalize_native_response(
            (question,),
            {"answers": {question.prompt: "Durability first (Recommended)"}},
        )
        state = tree.commit_snapshot(InterviewState(), snapshot, normalized)
        self.assertEqual(state.answers["delivery"].value, "Durability first")
        self.assertFalse(state.answers["delivery"].custom)

    def test_selected_answer_and_annotation_notes_are_preserved(self) -> None:
        question = DesignTree([root("delivery")]).snapshot(InterviewState()).questions[0]
        normalized = normalize_native_response(
            (question,),
            {
                "answers": {question.prompt: "Durability first (Recommended)"},
                "annotations": {
                    question.prompt: {"notes": "Only with deterministic generation"}
                },
            },
        )
        self.assertEqual(
            normalized["delivery"],
            "Durability first (Recommended) — Only with deterministic generation",
        )

    def test_other_and_free_form_response_are_preserved(self) -> None:
        question = DesignTree([root("scope")]).snapshot(InterviewState()).questions[0]
        normalized = normalize_native_response(
            (question,),
            {
                "answers": {question.prompt: "Other"},
                "response": "Keep both linked skills",
                "annotations": {question.prompt: {"notes": "Retain attribution"}},
            },
        )
        self.assertEqual(
            normalized["scope"], "Keep both linked skills — Retain attribution"
        )
        state = DesignTree([root("scope")]).commit_snapshot(
            InterviewState(),
            DesignTree([root("scope")]).snapshot(InterviewState()),
            normalized,
        )
        self.assertTrue(state.answers["scope"].custom)

    def test_unavailable_and_denied_fallback_is_explicit(self) -> None:
        question = DesignTree([root("delivery")]).snapshot(InterviewState()).questions[0]
        absent = Capabilities(False, True).fallback_reason or ""
        denied = Capabilities(True, False).fallback_reason or ""
        self.assertIn("not exposed", render_fallback((question,), absent))
        output = render_fallback((question,), denied)
        self.assertIn("Native questionnaire unavailable:", output)
        self.assertIn("denied", output)
        self.assertIn("Other: provide a custom answer", output)
        self.assertIn("Durability first (Recommended)", output)

    def test_schema_caps_and_native_other_are_enforced(self) -> None:
        question = DesignTree([root("delivery")]).snapshot(InterviewState()).questions[0]
        with self.assertRaisesRegex(ValueError, "question mark"):
            serialize_native((replace(question, prompt="Choose a direction"),))
        with self.assertRaisesRegex(ValueError, "one to four"):
            serialize_native((question,) * 5)
        with self.assertRaisesRegex(ValueError, "two to four options"):
            serialize_native(
                (
                    replace(
                        question,
                        options=(
                            *question.options,
                            Option("Balanced", "Balance delivery concerns."),
                            Option("Minimal", "Minimize the delivered scope."),
                            Option("Maximal", "Maximize the delivered scope."),
                        ),
                    ),
                )
            )
        with self.assertRaisesRegex(ValueError, "native Other"):
            serialize_native(
                (
                    replace(
                        question,
                        options=(
                            question.options[0],
                            Option("Other", "Provide custom text."),
                        ),
                    ),
                )
            )

    def test_final_confirmation_is_not_plan_approval(self) -> None:
        question = confirmation_question()
        native = serialize_native((question,))["questions"][0]
        self.assertFalse(native["multiSelect"])
        self.assertEqual(native["options"][0]["label"], "Confirmed (Recommended)")
        self.assertNotIn("ExitPlanMode", str(native))

        confirmed = resolve_confirmation("Confirmed (Recommended)")
        self.assertEqual(confirmed.disposition, ConfirmationDisposition.CONFIRMED)
        self.assertTrue(confirmed.may_finish_interview)
        self.assertFalse(confirmed.continue_interview)

        reopened = resolve_confirmation("Reopen")
        self.assertEqual(reopened.disposition, ConfirmationDisposition.REOPEN)
        self.assertTrue(reopened.continue_interview)
        custom = resolve_confirmation("We still need an offline decision")
        self.assertEqual(custom.disposition, ConfirmationDisposition.EXTEND)
        self.assertEqual(custom.concern, "We still need an offline decision")
        self.assertTrue(custom.extends_tree)


if __name__ == "__main__":
    unittest.main()
