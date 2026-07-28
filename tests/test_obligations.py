"""Tests for deriving reviewable test obligations from reachable authority."""

from __future__ import annotations

import json

import pytest

from agentmandate import loads
from agentmandate.obligations import (
    OBLIGATIONS_SCHEMA,
    Obligation,
    ObligationSet,
    derive,
    load_obligations,
    save_obligations,
    to_decision_suite,
)

MANDATE = """
agent: dispute-resolver
limits: {total: {amount: 500, currency: GBP}}
tools:
  - name: open_case
    effect: read
    produces: case
  - name: issue_refund
    effect: irreversible
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: {amount: 500, currency: GBP}
    requires_approval: true
  - name: post_ledger
    effect: write
    principal: service
    requires: [case]
  - name: unreachable_wipe
    effect: irreversible
    requires: [ghost_scope]
"""


def kinds(obligation_set):
    return {o.identifier for o in obligation_set.obligations}


class TestDerivationFollowsReachability:
    """A tool nobody can get to needs no test, and listing it would pad the
    review with work that protects nothing."""

    def test_an_unreachable_tool_produces_no_obligation(self):
        found = kinds(derive(loads(MANDATE)))
        assert not any("unreachable_wipe" in name for name in found)

    def test_a_reachable_irreversible_effect_is_an_obligation(self):
        assert "irreversible:issue_refund" in kinds(derive(loads(MANDATE)))

    def test_a_reachable_approval_gate_is_an_obligation(self):
        """A gate no test reaches has never been shown to hold."""
        assert "approval-required:issue_refund" in kinds(derive(loads(MANDATE)))

    def test_a_service_principal_is_an_obligation(self):
        assert "service-principal:post_ledger" in kinds(derive(loads(MANDATE)))

    def test_a_value_bearing_call_is_an_obligation_naming_its_ceiling(self):
        obligation = next(
            o for o in derive(loads(MANDATE)).obligations if o.kind == "value-bearing"
        )
        assert "500 GBP" in obligation.reason

    def test_a_plain_read_produces_no_obligation(self):
        assert not any("open_case" in name for name in kinds(derive(loads(MANDATE))))

    def test_a_mandate_with_no_consequential_authority_yields_none(self):
        plain = loads("agent: a\ntools:\n  - name: look\n    effect: read\n")
        result = derive(plain)

        assert result.obligations == ()
        assert "no consequential authority is reachable" in result.render()


class TestCompoundBreachesStayOut:
    """A cumulative-value path is a multi-call sequence, which is scenario
    testing rather than decision coverage."""

    def test_no_obligation_is_emitted_for_a_reachable_breach(self):
        minting = MANDATE.replace(
            "    produces: case\n", "    produces: case\n    unbounded: true\n"
        )
        found = {o.kind for o in derive(loads(minting)).obligations}

        assert "breach" not in found
        assert "cumulative_value" not in found


class TestDecisionsAreNeverInvented:
    """An effect class is an authority fact. A decision is an application
    label somebody chose. No parsing turns one into the other."""

    def test_a_fresh_obligation_carries_no_decision(self):
        assert all(not o.reviewed for o in derive(loads(MANDATE)).obligations)

    def test_a_suite_cannot_be_generated_before_review(self):
        with pytest.raises(ValueError, match="not fully reviewed yet"):
            to_decision_suite(derive(loads(MANDATE)))

    def test_a_decision_without_a_probe_is_only_half_reviewed(self):
        """A suite of placeholder inputs runs happily and measures nothing,
        which is worse than a file that refuses to load."""
        half = ObligationSet(
            agent="a",
            obligations=(
                Obligation("irreversible", "pay", "why", decision="paid"),
            ),
        )
        assert half.unreviewed == ("irreversible:pay",)
        with pytest.raises(ValueError, match="at least one probe"):
            to_decision_suite(half)

    def test_the_refusal_names_the_unmapped_obligations(self):
        with pytest.raises(ValueError) as info:
            to_decision_suite(derive(loads(MANDATE)))
        assert "irreversible:issue_refund" in str(info.value)

    def test_the_render_marks_each_unmapped_row(self):
        rendered = derive(loads(MANDATE)).render()
        assert "REVIEW: map a decision" in rendered
        assert "REVIEW: write at least one probe" in rendered


class TestReconciliation:
    """A reviewed file records decisions somebody mapped. It is not a
    substitute for the manifest, and trusting it alone lets a stale review
    generate a suite for authority the agent no longer has."""

    @staticmethod
    def fully_reviewed():
        return ObligationSet(
            agent="dispute-resolver",
            obligations=tuple(
                Obligation(o.kind, o.subject, o.reason, decision="refund_approved",
                           cases=(f"probe for {o.identifier}",))
                for o in derive(loads(MANDATE)).obligations
            ),
        )

    def test_a_matching_review_carries_over_by_identifier(self):
        from agentmandate.obligations import reconcile

        result = reconcile(derive(loads(MANDATE)), self.fully_reviewed())
        assert result.unreviewed == ()

    def test_an_obligation_the_manifest_no_longer_reaches_is_dropped(self):
        from agentmandate.obligations import reconcile

        shrunk = MANDATE.replace("    principal: service\n", "")
        result = reconcile(derive(loads(shrunk)), self.fully_reviewed())

        assert not any(o.kind == "service-principal" for o in result.obligations)

    def test_a_newly_reachable_obligation_appears_unreviewed(self):
        """The point of reconciling: new authority blocks generation until
        somebody has looked at it."""
        from agentmandate.obligations import reconcile

        grown = MANDATE + (
            "  - name: close_account\n"
            "    effect: irreversible\n"
            "    requires: [case]\n"
        )
        result = reconcile(derive(loads(grown)), self.fully_reviewed())

        assert "irreversible:close_account" in result.unreviewed

    def test_a_renamed_tool_loses_its_review(self):
        from agentmandate.obligations import reconcile

        renamed = MANDATE.replace("issue_refund", "issue_payout")
        result = reconcile(derive(loads(renamed)), self.fully_reviewed())

        assert result.unreviewed != ()
        assert any("issue_payout" in name for name in result.unreviewed)


class TestSuiteGeneration:
    @staticmethod
    def reviewed(mapping):
        return ObligationSet(
            agent="dispute-resolver",
            obligations=tuple(
                Obligation(
                    kind=o.kind,
                    subject=o.subject,
                    reason=o.reason,
                    decision=mapping.get(o.kind, "refund_approved"),
                    cases=(f"a reviewed probe for {o.identifier}",),
                )
                for o in derive(loads(MANDATE)).obligations
            ),
        )

    def test_a_reviewed_set_generates_a_loadable_suite(self):
        suite = to_decision_suite(self.reviewed({}))

        assert suite["schema"] == "agentverity.decision-suite/v1"
        assert suite["contract"]["allowed"] == ["refund_approved"]
        assert suite["cases"][0]["expected"] == "refund_approved"

    def test_consequence_classes_become_critical_decisions(self):
        suite = to_decision_suite(
            self.reviewed({"service-principal": "ledger_posted"})
        )
        # service-principal is a control concern, not a consequence class, so
        # its decision is required but not critical.
        assert "refund_approved" in suite["contract"]["critical"]
        assert "ledger_posted" not in suite["contract"]["critical"]

    def test_critical_can_be_suppressed(self):
        suite = to_decision_suite(self.reviewed({}), critical=False)
        assert "critical" not in suite["contract"]

    def test_case_inputs_come_from_the_reviewer(self):
        """Authority analysis cannot invent a probe that reaches a decision,
        so the suite carries what a human wrote rather than a placeholder."""
        suite = to_decision_suite(self.reviewed({}))

        assert all(not c["input"].startswith("REVIEW") for c in suite["cases"])
        assert suite["cases"][0]["input"].startswith("a reviewed probe for")

    def test_the_same_probe_reviewed_twice_is_refused(self):
        duplicated = ObligationSet(
            agent="a",
            obligations=(
                Obligation("irreversible", "pay", "why", decision="paid", cases=("same",)),
                Obligation("value-bearing", "pay", "why", decision="paid", cases=("same",)),
            ),
        )
        with pytest.raises(ValueError, match="reviewed twice"):
            to_decision_suite(duplicated)

    def test_an_empty_reviewed_set_is_refused(self):
        with pytest.raises(ValueError, match="no obligations"):
            to_decision_suite(ObligationSet(agent="a", obligations=()))


class TestRoundTrip:
    def test_identifiers_survive_regeneration_so_review_is_not_lost(self):
        first = derive(loads(MANDATE))
        second = derive(loads(MANDATE))
        assert [o.identifier for o in first.obligations] == [
            o.identifier for o in second.obligations
        ]

    def test_obligations_survive_a_file_round_trip(self, tmp_path):
        path = tmp_path / "obligations.json"
        original = derive(loads(MANDATE))
        save_obligations(original, path)
        restored = load_obligations(path)

        assert restored.agent == original.agent
        assert kinds(restored) == kinds(original)

    @pytest.mark.parametrize(
        "payload, message",
        [
            ([], "root must be an object"),
            ({"schema": "nope"}, "unsupported obligations schema"),
            ({"schema": OBLIGATIONS_SCHEMA, "obligations": {}}, "must be a list"),
            (
                {"schema": OBLIGATIONS_SCHEMA, "obligations": ["x"]},
                "must be an object",
            ),
            (
                {"schema": OBLIGATIONS_SCHEMA, "obligations": [{"kind": "x"}]},
                "missing subject",
            ),
        ],
    )
    def test_malformed_files_are_rejected(self, payload, message):
        with pytest.raises(ValueError, match=message):
            ObligationSet.from_dict(payload)

    def test_a_missing_file_is_reported(self, tmp_path):
        with pytest.raises(ValueError, match="cannot load obligations"):
            load_obligations(tmp_path / "absent.json")

    def test_the_shipped_reviewed_example_generates_a_suite(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        reviewed = load_obligations(root / "examples/reviewed-obligations.json")
        suite = to_decision_suite(reviewed)

        assert json.dumps(suite)  # serialisable
        assert reviewed.unreviewed == ()
