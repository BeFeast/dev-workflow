from __future__ import annotations

import unittest

from dev_workflow.grilling import Decision, DesignTree, InterviewState, Option


def decision(
    decision_id: str,
    *,
    depends_on: frozenset[str] = frozenset(),
    facts_required: frozenset[str] = frozenset(),
) -> Decision:
    return Decision(
        id=decision_id,
        header=decision_id[:12],
        prompt=f"Choose {decision_id}",
        options=(
            Option("Preferred", "The recommended balanced choice."),
            Option("Alternate", "A valid choice with a different trade-off."),
        ),
        depends_on=depends_on,
        facts_required=facts_required,
    )


class DesignTreeTests(unittest.TestCase):
    def test_frontier_waits_for_decisions_and_discoverable_facts(self) -> None:
        tree = DesignTree(
            [
                decision("root"),
                decision("fact_gate", facts_required=frozenset({"repo_state"})),
                decision("child", depends_on=frozenset({"root"})),
            ]
        )
        state = InterviewState()
        self.assertEqual(tree.snapshot(state).ids, ("root",))
        self.assertFalse(tree.complete(state))
        self.assertEqual(
            tuple(item.id for item in tree.blocked_on_facts(state)), ("fact_gate",)
        )

        state = state.with_facts({"repo_state"})
        snapshot = tree.snapshot(state)
        self.assertEqual(snapshot.ids, ("root", "fact_gate"))
        state = tree.commit_snapshot(
            state,
            snapshot,
            {"root": "Preferred", "fact_gate": "Alternate"},
        )
        self.assertEqual(tree.snapshot(state).ids, ("child",))
        self.assertFalse(tree.complete(state))
        child = tree.snapshot(state)
        state = tree.commit_snapshot(state, child, {"child": "Preferred"})
        self.assertTrue(tree.complete(state))

    def test_partial_snapshot_cannot_be_committed(self) -> None:
        tree = DesignTree([decision("one"), decision("two")])
        snapshot = tree.snapshot(InterviewState())
        with self.assertRaisesRegex(ValueError, "must be complete"):
            tree.commit_snapshot(InterviewState(), snapshot, {"one": "Preferred"})

    def test_recommended_native_suffix_normalizes_to_known_option(self) -> None:
        tree = DesignTree([decision("shape")])
        snapshot = tree.snapshot(InterviewState())
        state = tree.commit_snapshot(
            InterviewState(), snapshot, {"shape": "Preferred (Recommended)"}
        )
        answer = state.answers["shape"]
        self.assertEqual(answer.value, "Preferred")
        self.assertFalse(answer.custom)

    def test_free_form_other_is_preserved_as_custom(self) -> None:
        tree = DesignTree([decision("shape")])
        snapshot = tree.snapshot(InterviewState())
        state = tree.commit_snapshot(
            InterviewState(), snapshot, {"shape": "Use the existing contract verbatim"}
        )
        answer = state.answers["shape"]
        self.assertEqual(answer.value, "Use the existing contract verbatim")
        self.assertTrue(answer.custom)

    def test_cycles_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cycle"):
            DesignTree(
                [
                    decision("one", depends_on=frozenset({"two"})),
                    decision("two", depends_on=frozenset({"one"})),
                ]
            )


if __name__ == "__main__":
    unittest.main()
