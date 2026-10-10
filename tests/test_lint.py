import pytest

from agentmandate import analyse, check, loads
from agentmandate.lint import ERROR, WARNING

CLEAN = """
agent: clean
limits:
  total: { amount: 500, currency: GBP }
tools:
  - name: open_case
    effect: read
    produces: case
  - name: issue_refund
    effect: irreversible
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: { amount: 500, currency: GBP }
    requires_approval: true
"""


def rules(mandate_text):
    return {finding.rule for finding in check(loads(mandate_text))}


def test_a_well_formed_mandate_produces_no_findings():
    assert check(loads(CLEAN)) == []


@pytest.mark.parametrize("effect", ["read", "write", "irreversible"])
def test_missing_scope_producer_is_an_error_for_every_effect_class(effect):
    mandate = loads(f"""
agent: dangling
tools:
  - name: use_case
    effect: {effect}
    requires: [case]
    requires_approval: true
""")
    findings = check(mandate)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule == "scope.missing-producer"
    assert finding.severity == ERROR and finding.subject == "use_case"
    assert "requires 'case'" in finding.message
    assert "unreachable in the declared model" in finding.message
    assert "genuine producers or remove unsupported requirements" in finding.message
    assert analyse(mandate).reachable_tools == frozenset()


def test_missing_requirements_are_reported_per_tool_without_flagging_produced_scopes():
    mandate = loads("""
agent: partially-modelled
tools:
  - name: lookup_case
    effect: read
    produces: case
  - name: use_case
    effect: read
    requires: [case]
  - name: join
    effect: read
    requires: [zeta, case, alpha]
  - name: another
    effect: read
    requires: [zeta]
""")
    findings = check(mandate)
    assert [(f.rule, f.subject) for f in findings] == [
        ("scope.missing-producer", "another"),
        ("scope.missing-producer", "join"),
    ]
    assert "requires 'alpha', 'zeta'" in findings[1].message
    assert "'case'" not in findings[1].message


def test_producer_can_follow_consumer_and_resolve_the_dangling_reference():
    mandate = loads("""
agent: ordered
tools:
  - name: use_case
    effect: read
    requires: [case]
  - name: find_case
    effect: read
    produces: case
""")
    assert check(mandate) == []
    assert analyse(mandate).reachable_tools == frozenset({"use_case", "find_case"})


def test_producer_existence_does_not_claim_cyclic_requirements_are_reachable():
    mandate = loads("""
agent: cyclic
tools:
  - name: cycle
    effect: read
    requires: [case]
    produces: case
""")
    assert check(mandate) == []
    assert analyse(mandate).reachable_tools == frozenset()


def test_separation_of_duties_flags_one_identity_holding_both_roles():
    text = (
        CLEAN
        + """
  - name: approve_refund
    effect: write
    requires: [case]
roles:
  proposer: [issue_refund]
  approver: [approve_refund]
"""
    )
    assert "sod.single-identity" in rules(text)


def test_separation_of_duties_flags_a_tool_that_approves_itself():
    text = (
        CLEAN
        + """
roles:
  proposer: [issue_refund]
  approver: [issue_refund]
"""
    )
    found = rules(text)
    assert "sod.same-tool" in found
    assert "sod.single-identity" in found


def test_no_separation_finding_when_only_one_side_is_declared():
    text = CLEAN + "roles:\n  proposer: [issue_refund]\n"
    assert not {r for r in rules(text) if r.startswith("sod.")}


def test_an_irreversible_effect_without_approval_is_an_error():
    text = CLEAN.replace("    requires_approval: true\n", "")
    findings = [f for f in check(loads(text)) if f.rule == "effect.ungated-irreversible"]
    assert len(findings) == 1
    assert findings[0].severity == ERROR


def test_a_service_principal_on_a_writing_tool_is_an_error():
    text = (
        CLEAN
        + """
  - name: ledger
    effect: write
    principal: service
    requires: [case]
"""
    )
    finding = next(f for f in check(loads(text)) if f.rule == "identity.service-principal")
    assert finding.severity == ERROR
    assert "confused-deputy" in finding.message


def test_service_principal_remediation_names_its_own_limit():
    text = (
        CLEAN
        + """
  - name: ledger
    effect: write
    principal: service
    requires: [case]
"""
    )
    finding = next(f for f in check(loads(text)) if f.rule == "identity.service-principal")

    # Actionable for the ordinary service-account case...
    assert "exchange" in finding.message
    # ...without claiming token exchange is always available or complete.
    assert "not always available" in finding.message
    assert "delegated user token" in finding.message
    assert "intersect other principals" in finding.message
    assert "named review" in finding.message


def test_a_service_principal_on_a_read_is_only_a_warning():
    text = (
        CLEAN
        + """
  - name: lookup
    effect: read
    principal: service
    requires: [case]
"""
    )
    finding = next(f for f in check(loads(text)) if f.rule == "identity.service-principal")
    assert finding.severity == WARNING


def test_a_ceiling_scoped_to_something_the_tool_does_not_require():
    text = CLEAN.replace("    requires: [case]\n    value_arg", "    value_arg")
    assert "ceiling.unbound-scope" in rules(text)


def test_unbounded_without_produces_is_a_warning():
    text = CLEAN + "  - name: noop\n    effect: read\n    unbounded: true\n"
    finding = next(f for f in check(loads(text)) if f.rule == "scope.unbounded-nothing")
    assert finding.severity == WARNING


def test_mixed_currencies_cannot_be_summed():
    text = (
        CLEAN
        + """
  - name: pay_usd
    effect: write
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: { amount: 10, currency: USD }
"""
    )
    assert "ceiling.mixed-currency" in rules(text)


def test_findings_are_ordered_worst_first():
    text = (
        CLEAN
        + """
  - name: noop
    effect: read
    unbounded: true
  - name: wipe
    effect: irreversible
    requires: [case]
"""
    )
    severities = [f.severity for f in check(loads(text))]
    assert severities == sorted(severities, key=lambda s: 0 if s == ERROR else 1)


def test_a_finding_renders_rule_subject_and_message():
    text = CLEAN.replace("    requires_approval: true\n", "")
    rendered = check(loads(text))[0].render()
    assert "ERROR" in rendered
    assert "effect.ungated-irreversible" in rendered
    assert "issue_refund" in rendered
