from __future__ import annotations

from dataclasses import replace

import pytest

from agentmandate import loads
from agentmandate._ir import (
    MANIFEST_PREDICATES,
    AuthorityIR,
    Entity,
    Evidence,
    Fact,
    IRFormatError,
    Source,
    _analyse_ir,
    _edge_id,
    _entity_id,
    _fact_id,
    _from_mandate,
    _to_mandate,
    _validate_profile_value,
)

MANIFEST = """
agent: profile
identity: spiffe://example/agent/profile
limits:
  total: {amount: 100, currency: GBP}
  depth: 4
  effects: {irreversible: 1}
roles:
  operator: [open_case, pay]
tools:
  - name: open_case
    effect: write
    produces: case
    unbounded: true
  - name: pay
    effect: irreversible
    principal: service
    requires: [case]
    value_arg: amount
    ceiling: {amount: 100, currency: GBP}
    scope_key: case
    requires_approval: true
"""


def snapshot() -> AuthorityIR:
    return _from_mandate(loads(MANIFEST))


def replace_fact(
    snapshot_value: AuthorityIR, subject: str, predicate: str, **changes
) -> AuthorityIR:
    fact = next(
        fact
        for fact in snapshot_value.facts
        if fact.subject == subject and fact.predicate == predicate
    )
    changed = replace(fact, **changes)
    return replace(
        snapshot_value,
        facts=tuple(
            changed if candidate == fact else candidate for candidate in snapshot_value.facts
        ),
    )


def test_manifest_predicate_registry_is_closed_and_profile_round_trips() -> None:
    value = snapshot()

    assert set(MANIFEST_PREDICATES) == {
        ("agent", "identity"),
        ("agent", "name"),
        ("agent", "roles"),
        ("agent", "tools"),
        ("constraint", "depth"),
        ("constraint", "effects"),
        ("constraint", "name"),
        ("constraint", "total"),
        ("principal", "name"),
        ("role", "members"),
        ("role", "name"),
        ("scope", "name"),
        ("tool", "ceiling"),
        ("tool", "effect"),
        ("tool", "name"),
        ("tool", "principal"),
        ("tool", "produces"),
        ("tool", "requires"),
        ("tool", "requires_approval"),
        ("tool", "scope_key"),
        ("tool", "unbounded"),
        ("tool", "value_arg"),
    }
    assert _to_mandate(value) == loads(MANIFEST)
    assert _to_mandate(_analyse_ir(value).graph) == loads(MANIFEST)


@pytest.mark.parametrize(
    ("field", "state", "message"),
    [
        ("review", "contested", "review is not accepted"),
        ("review", "unreviewed", "review is not accepted"),
        ("confidence", "heuristic", "confidence is not exact"),
        ("confidence", "unknown", "confidence is not exact"),
    ],
)
def test_valid_archival_evidence_is_not_automatically_eligible_for_analysis(
    field: str, state: str, message: str
) -> None:
    value = snapshot()
    effect = next(fact for fact in value.facts if fact.predicate == "effect")
    evidence = replace(effect.evidence[0], **{field: state})
    changed = replace_fact(value, effect.subject, "effect", evidence=(evidence,))

    changed.validate()
    with pytest.raises(IRFormatError, match=message):
        _analyse_ir(changed)


def test_unknown_predicates_are_archivable_but_not_analyzable() -> None:
    value = snapshot()
    extra = Fact(
        id=_fact_id("tool:pay", "flavor"),
        subject="tool:pay",
        predicate="flavor",
        value="opaque",
        evidence=(Evidence("source:mandate", "/tools/1/flavor"),),
    )
    changed = replace(value, facts=value.facts + (extra,))

    changed.validate()
    with pytest.raises(IRFormatError, match="predicate is unsupported"):
        _to_mandate(changed)


def test_wrong_value_shapes_fail_as_ir_errors_before_projection() -> None:
    value = replace_fact(snapshot(), "tool:pay", "ceiling", value="opaque")

    value.validate()
    with pytest.raises(IRFormatError, match="schema nullable_money"):
        _analyse_ir(value)

    default_backed = _from_mandate(
        loads("agent: defaults\ntools:\n  - name: look\n    effect: read\n")
    )
    default_backed = replace_fact(default_backed, "tool:look", "ceiling", value="opaque")
    with pytest.raises(IRFormatError, match=r"facts\[.*\]\.value.*nullable_money"):
        _to_mandate(default_backed)


@pytest.mark.parametrize(
    ("subject", "predicate", "bad_value", "schema"),
    [
        ("agent:profile", "identity", 7, "nullable_string"),
        ("tool:pay", "value_arg", "", "nullable_name"),
        ("tool:pay", "effect", "opaque", "effect"),
        ("tool:pay", "requires_approval", 1, "boolean"),
        ("constraint:run", "depth", True, "positive_integer"),
        ("constraint:run", "effects", {"read": -1}, "effect_limits"),
        ("tool:pay", "requires", "scope:case", "scope_refs"),
    ],
)
def test_each_manifest_value_schema_fails_closed(
    subject: str, predicate: str, bad_value: object, schema: str
) -> None:
    value = replace_fact(snapshot(), subject, predicate, value=bad_value)

    with pytest.raises(IRFormatError, match=f"schema {schema}"):
        _to_mandate(value)


@pytest.mark.parametrize(
    "money",
    [
        {"amount": 1, "currency": "GBP"},
        {"amount": "NaN", "currency": "GBP"},
        {"amount": "1", "currency": "gbp"},
        {"amount": "1", "currency": "GB"},
        {"amount": "1", "currency": "GBP", "extra": "field"},
    ],
)
def test_money_profile_requires_canonical_decimal_strings(money: object) -> None:
    value = replace_fact(snapshot(), "tool:pay", "ceiling", value=money)

    with pytest.raises(IRFormatError, match="schema nullable_money"):
        _to_mandate(value)


def test_profile_reference_schemas_check_kind_and_principal_vocabulary() -> None:
    tool = Entity("tool:t", "tool", "t")
    scope = Entity("scope:s", "scope", "s")
    principal = Entity("principal:robot", "principal", "robot")
    entities = {entity.id: entity for entity in (tool, scope, principal)}

    with pytest.raises(IRFormatError, match="schema principal_ref"):
        _validate_profile_value(principal.id, "principal_ref", "facts[0].value", tool, entities)
    with pytest.raises(IRFormatError, match="schema nullable_scope_ref"):
        _validate_profile_value(tool.id, "nullable_scope_ref", "facts[0].value", tool, entities)


def test_profile_requires_supported_adapters_and_exact_source_digests() -> None:
    value = snapshot()
    mandate_source = next(source for source in value.sources if source.id == "source:mandate")
    unsupported = replace(mandate_source, adapter="external.adapter")
    changed = replace(
        value,
        sources=tuple(
            unsupported if source == mandate_source else source for source in value.sources
        ),
    )
    changed.validate()
    with pytest.raises(IRFormatError, match="outside the analyzable manifest-v1 profile"):
        _to_mandate(changed)

    wrong_digest = replace(mandate_source, semantic_sha256="0" * 64)
    changed = replace(
        value,
        sources=tuple(
            wrong_digest if source == mandate_source else source for source in value.sources
        ),
    )
    with pytest.raises(IRFormatError, match="semantic_sha256 does not match"):
        _to_mandate(changed)


def test_profile_rejects_missing_or_false_default_provenance() -> None:
    value = snapshot()
    effect = next(fact for fact in value.facts if fact.predicate == "effect")
    without_evidence = replace_fact(value, effect.subject, "effect", evidence=())
    with pytest.raises(IRFormatError, match="evidence is empty"):
        _to_mandate(without_evidence)

    schema_evidence = Evidence("source:manifest-v1", "manifest:v1#/defaults/tool.effect")
    false_default = replace_fact(
        value,
        effect.subject,
        "effect",
        evidence=effect.evidence + (schema_evidence,),
    )
    with pytest.raises(IRFormatError, match="inapplicable schema default"):
        _to_mandate(false_default)


def test_profile_rejects_unsupported_entities_and_incomplete_tool_sets() -> None:
    value = snapshot()
    extra = Entity(_entity_id("inventory", "external"), "inventory", "external")
    with pytest.raises(IRFormatError, match="entities.*kind is outside"):
        _to_mandate(replace(value, entities=value.entities + (extra,)))

    declared_tools = next(
        fact
        for fact in value.facts
        if fact.subject == "agent:profile" and fact.predicate == "tools"
    )
    incomplete = replace_fact(value, "agent:profile", "tools", value=declared_tools.value[:-1])
    with pytest.raises(IRFormatError, match="agent tools do not cover"):
        _to_mandate(incomplete)


def test_profile_requires_exact_sources_and_reviewed_manifest_support() -> None:
    value = snapshot()
    extra = Source(
        id="source:extra",
        kind="mandate-semantic",
        locator="memory:extra",
        format_version=1,
        producer_version=None,
        semantic_sha256="0" * 64,
        adapter="agentmandate.manifest",
        adapter_version=2,
    )
    with pytest.raises(IRFormatError, match="sources do not match"):
        _to_mandate(replace(value, sources=value.sources + (extra,)))

    effect = next(fact for fact in value.facts if fact.predicate == "effect")
    schema_only = replace_fact(
        value,
        effect.subject,
        "effect",
        evidence=(Evidence("source:manifest-v1", "/defaults/effect"),),
    )
    with pytest.raises(IRFormatError, match="lacks reviewed manifest support"):
        _to_mandate(schema_only)


def test_profile_requires_complete_roles_scopes_and_principals() -> None:
    value = snapshot()
    without_role = replace_fact(value, "agent:profile", "roles", value=[])
    with pytest.raises(IRFormatError, match="agent roles do not cover"):
        _to_mandate(without_role)

    extra_scope = Entity("scope:extra", "scope", "extra")
    extra_name = Fact(
        _fact_id(extra_scope.id, "name"),
        extra_scope.id,
        "name",
        "extra",
        (Evidence("source:mandate", "/extra"),),
    )
    with pytest.raises(IRFormatError, match="scope entities do not match"):
        _to_mandate(
            replace(
                value,
                entities=value.entities + (extra_scope,),
                facts=value.facts + (extra_name,),
            )
        )

    principal = next(
        fact
        for fact in value.facts
        if fact.subject == "tool:open_case" and fact.predicate == "principal"
    )
    service_only = replace_fact(
        value,
        "tool:open_case",
        "principal",
        value="principal:service",
        evidence=(principal.evidence[0],),
    )
    old_edge = next(
        edge
        for edge in service_only.edges
        if edge.source == "tool:open_case" and edge.relation == "acts_as"
    )
    new_edge = replace(
        old_edge,
        id=_edge_id("tool:open_case", "acts_as", "principal:service"),
        target="principal:service",
    )
    service_only = replace(
        service_only,
        edges=tuple(new_edge if edge == old_edge else edge for edge in service_only.edges),
    )
    with pytest.raises(IRFormatError, match="principal entities do not match"):
        _to_mandate(service_only)


def test_profile_rechecks_manifest_cross_field_rules() -> None:
    value = snapshot()
    without_ceiling = replace_fact(value, "tool:pay", "ceiling", value=None)
    with pytest.raises(IRFormatError, match="ceiling and value_arg"):
        _to_mandate(without_ceiling)

    without_scope_key = replace_fact(value, "tool:pay", "scope_key", value=None)
    ceiling_edge = next(
        edge
        for edge in without_scope_key.edges
        if edge.source == "tool:pay" and edge.relation == "ceiling_on"
    )
    without_scope_key = replace(
        without_scope_key,
        edges=tuple(edge for edge in without_scope_key.edges if edge != ceiling_edge),
    )
    with pytest.raises(IRFormatError, match="scope_key is required"):
        _to_mandate(without_scope_key)


def test_profile_requires_the_run_constraint_and_default_digest() -> None:
    value = snapshot()
    constraint = next(entity for entity in value.entities if entity.kind == "constraint")
    replacement = Entity("constraint:not-run", "constraint", "not-run")
    facts = tuple(
        replace(
            fact,
            id=_fact_id(replacement.id, fact.predicate),
            subject=replacement.id,
            value=replacement.name if fact.predicate == "name" else fact.value,
        )
        if fact.subject == constraint.id
        else fact
        for fact in value.facts
    )
    changed = replace(
        value,
        entities=tuple(
            replacement if entity == constraint else entity for entity in value.entities
        ),
        facts=facts,
    )
    with pytest.raises(IRFormatError, match="requires the run constraint"):
        _to_mandate(changed)

    defaults = next(source for source in value.sources if source.id == "source:manifest-v1")
    wrong_digest = replace(defaults, semantic_sha256="0" * 64)
    changed = replace(
        value,
        sources=tuple(wrong_digest if source == defaults else source for source in value.sources),
    )
    with pytest.raises(IRFormatError, match="source:manifest-v1 semantic_sha256"):
        _to_mandate(changed)


def test_profile_rejects_name_mismatch_invalid_decimal_and_unknown_schema() -> None:
    value = replace_fact(snapshot(), "tool:pay", "name", value="other")
    with pytest.raises(IRFormatError, match="schema entity_name"):
        _to_mandate(value)

    value = replace_fact(
        snapshot(),
        "tool:pay",
        "ceiling",
        value={"amount": "not-a-number", "currency": "GBP"},
    )
    with pytest.raises(IRFormatError, match="schema nullable_money"):
        _to_mandate(value)

    tool = Entity("tool:t", "tool", "t")
    with pytest.raises(IRFormatError, match="unknown manifest profile schema"):
        _validate_profile_value("value", "invented", "facts[0].value", tool, {tool.id: tool})
