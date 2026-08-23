import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from agentmandate import load
from agentmandate._inventory import (
    DynamicInventory,
    InventoryFormatError,
    _inventory_semantic_sha256,
    _validate_inventory_profile,
    reconcile,
)
from agentmandate._ir import AuthorityIR, Entity, Fact
from agentmandate.drift import WITHHELD, compare
from agentmandate.inventory import Binding, Inventory, collect

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
AGENTKIT = FIXTURES / "dynamic-inventory-agentkit-v1.json"
SENTRY = FIXTURES / "dynamic-inventory-sentry-v1.json"


def raw_fixture(path: Path = AGENTKIT) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def encoded(raw: object) -> str:
    return json.dumps(raw, separators=(",", ":"))


@pytest.mark.parametrize(
    ("fixture", "source", "complete", "members"),
    [
        (
            AGENTKIT,
            ROOT / "docs" / "evidence" / "agentkit" / "inventory-v074.json",
            "complete",
            20,
        ),
        (
            SENTRY,
            ROOT / "docs" / "evidence" / "sentry-mcp" / "catalogue.json",
            "partial",
            8,
        ),
    ],
)
def test_canonical_evidence_fixtures_round_trip_and_verify_source(
    fixture: Path, source: Path, complete: str, members: int
) -> None:
    text = fixture.read_text(encoding="utf-8")
    declaration = DynamicInventory.from_json(text)

    assert declaration.to_json() == text
    assert declaration.membership.completeness == complete
    assert len(declaration.membership.members) == members
    declaration.verify_source(source.read_bytes())


def test_agentkit_members_are_the_distinct_preserved_provider_actions() -> None:
    source = json.loads(
        (ROOT / "docs" / "evidence" / "agentkit" / "inventory-v074.json").read_text(
            encoding="utf-8"
        )
    )
    actions = [tool for provider in source["providers"] for tool in provider["tools"]]
    declaration = DynamicInventory.from_json(AGENTKIT.read_text(encoding="utf-8"))

    assert len(actions) == 21
    assert len(set(actions)) == 20
    assert set(declaration.membership.members) == set(actions)


def test_sentry_partial_members_are_exactly_the_visible_catalogue() -> None:
    source = json.loads(
        (ROOT / "docs" / "evidence" / "sentry-mcp" / "catalogue.json").read_text(
            encoding="utf-8"
        )
    )
    declaration = DynamicInventory.from_json(SENTRY.read_text(encoding="utf-8"))

    assert set(declaration.membership.members) == {
        tool["name"] for tool in source["tools"]
    }
    assert declaration.membership.completeness == "partial"


def test_canonicalization_sorts_members_selection_keys_and_list_values() -> None:
    raw = raw_fixture()
    raw["membership"]["members"].reverse()
    raw["selection"] = {
        "skills": ["triage", "inspect"],
        "environment": "production",
    }

    declaration = DynamicInventory.from_json(encoded(raw))
    rendered = declaration.as_dict()

    assert list(rendered["selection"]) == ["environment", "skills"]
    assert rendered["selection"]["skills"] == ["inspect", "triage"]
    assert rendered["membership"]["members"] == sorted(
        rendered["membership"]["members"]
    )


def test_an_empty_selection_is_valid() -> None:
    raw = raw_fixture()
    raw["selection"] = {}

    assert DynamicInventory.from_json(encoded(raw)).selection == ()


def test_source_verification_rejects_tampering_and_non_bytes() -> None:
    declaration = DynamicInventory.from_json(AGENTKIT.read_text(encoding="utf-8"))

    with pytest.raises(InventoryFormatError, match="does not match supplied bytes"):
        declaration.verify_source(b"tampered")
    with pytest.raises(InventoryFormatError, match="content must be bytes"):
        declaration.verify_source("not bytes")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(inventory_version=True), "version type"),
        (lambda raw: raw.update(inventory_version=2), "version 2"),
        (lambda raw: raw["boundary"].update(id=""), "id must be a non-empty string"),
        (lambda raw: raw["boundary"].update(id=" padded "), "non-empty string"),
        (lambda raw: raw["boundary"].update(kind="other"), "kind has an invalid value"),
        (
            lambda raw: raw["boundary"]["target"].update(source="/absolute.py"),
            "safe relative POSIX path",
        ),
        (
            lambda raw: raw["boundary"]["target"].update(source="../agent.py"),
            "safe relative POSIX path",
        ),
        (
            lambda raw: raw["boundary"]["target"].update(source="src\\agent.py"),
            "safe relative POSIX path",
        ),
        (
            lambda raw: raw["boundary"]["target"].update(source="src/./agent.py"),
            "safe relative POSIX path",
        ),
        (
            lambda raw: raw["boundary"]["target"].update(source="."),
            "safe relative POSIX path",
        ),
        (lambda raw: raw.update(selection=[]), "selection must be an object"),
        (lambda raw: raw.update(selection={"token": "unsafe"}), "unsupported key"),
        (lambda raw: raw.update(selection={"skills": ""}), "non-empty string"),
        (lambda raw: raw.update(selection={"skills": []}), "non-empty string"),
        (
            lambda raw: raw.update(selection={"skills": ["inspect", "inspect"]}),
            "must not contain duplicates",
        ),
        (
            lambda raw: raw["source"].update(content_sha256="A" * 64),
            "lowercase SHA-256",
        ),
        (
            lambda raw: raw["source"].update(locator="../capture.json"),
            "safe relative POSIX path",
        ),
        (
            lambda raw: raw["membership"].update(relation="contains_agent"),
            "relation has an invalid value",
        ),
        (
            lambda raw: raw["membership"].update(completeness="mostly"),
            "completeness has an invalid value",
        ),
        (
            lambda raw: raw["membership"].update(members="tool"),
            "array of non-empty strings",
        ),
        (
            lambda raw: raw["membership"].update(members=[""]),
            "array of non-empty strings",
        ),
        (
            lambda raw: raw["membership"].update(members=["tool", "tool"]),
            "must not contain duplicates",
        ),
        (
            lambda raw: raw["evidence"].update(confidence="certain"),
            "confidence has an invalid value",
        ),
        (
            lambda raw: raw["evidence"].update(review="pending"),
            "review has an invalid value",
        ),
        (
            lambda raw: raw["evidence"].update(reviewer=7),
            "reviewer must be a non-empty string or null",
        ),
        (
            lambda raw: raw["evidence"].update(review="unreviewed"),
            "unreviewed evidence cannot name",
        ),
        (
            lambda raw: raw["evidence"].update(reviewer=None),
            "reviewed evidence requires",
        ),
        (
            lambda raw: raw["evidence"].update(expires="not-a-date"),
            "must be an ISO calendar date",
        ),
        (
            lambda raw: raw["evidence"].update(expires="20300101"),
            "must be an ISO calendar date",
        ),
    ],
)
def test_invalid_semantic_shapes_are_typed_and_value_safe(mutate, message: str) -> None:
    raw = raw_fixture()
    mutate(raw)

    with pytest.raises(InventoryFormatError, match=message) as caught:
        DynamicInventory.from_json(encoded(raw))

    assert "unsafe" not in str(caught.value)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{", "not valid JSON at line 1 column 2"),
        ("NaN", "not valid JSON"),
        ("[]", "root must be an object"),
        ("{}", "missing field 'inventory_version'"),
        (None, "not valid JSON"),
    ],
)
def test_invalid_roots_use_one_typed_error_boundary(text, message: str) -> None:
    with pytest.raises(InventoryFormatError, match=message):
        DynamicInventory.from_json(text)  # type: ignore[arg-type]


def test_unknown_and_missing_fields_are_rejected() -> None:
    raw = raw_fixture()
    raw["extra"] = "sensitive-value"
    with pytest.raises(InventoryFormatError, match="root has unknown field 'extra'") as caught:
        DynamicInventory.from_json(encoded(raw))
    assert "sensitive-value" not in str(caught.value)

    raw = raw_fixture()
    del raw["source"]["producer"]
    with pytest.raises(InventoryFormatError, match="source is missing field 'producer'"):
        DynamicInventory.from_json(encoded(raw))


def test_records_must_be_objects() -> None:
    for field in ("boundary", "source", "membership", "evidence"):
        raw = raw_fixture()
        raw[field] = []
        with pytest.raises(InventoryFormatError, match=f"{field} must be an object"):
            DynamicInventory.from_json(encoded(raw))

    raw = raw_fixture()
    raw["boundary"]["target"] = []
    with pytest.raises(InventoryFormatError, match="boundary.target must be an object"):
        DynamicInventory.from_json(encoded(raw))


def test_unreviewed_evidence_has_no_clock_fields() -> None:
    raw = raw_fixture()
    raw["evidence"] = {
        "confidence": "unknown",
        "review": "unreviewed",
        "reviewer": None,
        "expires": None,
    }

    evidence = DynamicInventory.from_json(encoded(raw)).evidence

    assert evidence.reviewer is None
    assert evidence.expires is None


def declaration(path: Path = AGENTKIT) -> DynamicInventory:
    return DynamicInventory.from_json(path.read_text(encoding="utf-8"))


def source_bytes(value: DynamicInventory) -> dict[str, bytes]:
    return {value.source.locator: (ROOT / value.source.locator).read_bytes()}


def selected_inventory(module: str, binding: str, unresolved: str = "provider()") -> Inventory:
    site = Binding(
        label=binding,
        where=f"{module}:1",
        module=module,
        callee="Agent",
        references=(),
        unresolved=(unresolved,),
        listed=False,
        recognised=True,
    )
    return Inventory(selected=site, bindings=[site], unresolved=[f"{site.where}: {unresolved}"])


def test_inventory_projection_has_closed_provenance_bearing_membership() -> None:
    value = declaration()

    graph = value.to_ir()
    reread = AuthorityIR.from_json(graph.to_json())
    _validate_inventory_profile(reread)

    assert len(graph.sources) == 2
    assert len([entity for entity in graph.entities if entity.kind == "boundary"]) == 1
    assert len([entity for entity in graph.entities if entity.kind == "tool"]) == 20
    assert len(graph.edges) == 20
    assert {edge.relation for edge in graph.edges} == {"contains_tool"}
    members_fact = next(fact for fact in graph.facts if fact.predicate == "members")
    assert all(edge.support == (members_fact.id,) for edge in graph.edges)
    assert {fact.evidence[0].location for fact in graph.facts} >= {
        "/boundary/target",
        "/membership/members",
        "/membership/members/0",
    }


def test_complete_agentkit_boundary_discharges_static_uncertainty(tmp_path: Path) -> None:
    source = tmp_path / "python" / "examples" / "strands-agents-cdp-server-chatbot"
    source.mkdir(parents=True)
    (source / "chatbot.py").write_text(
        "tools = get_strands_tools(agentkit)\nagent = Agent(tools=tools)\n",
        encoding="utf-8",
    )
    value = declaration()
    inventory = collect(tmp_path)

    result = reconcile(
        inventory,
        [value],
        source_bytes(value),
        selection=dict(value.selection),
        as_of=date(2027, 1, 1),
    )
    drift = compare(load(ROOT / "docs/evidence/agentkit/mandate.yaml"), inventory, dynamic=result)

    assert result.complete
    assert result.covers_binding
    assert result.as_of == "2027-01-01"
    assert len(result.graphs) == 1
    assert drift.clean
    assert len(drift.discovered) == 20


def test_partial_sentry_boundary_widens_but_cannot_claim_completeness() -> None:
    value = declaration(SENTRY)
    inventory = selected_inventory(
        "docs/evidence/sentry-mcp/capture-catalogue.mjs", "tools/list"
    )

    result = reconcile(
        inventory,
        [value],
        source_bytes(value),
        selection=dict(value.selection),
        as_of=date(2027, 1, 1),
    )
    drift = compare(load(ROOT / "docs/evidence/sentry-mcp/mandate.yaml"), inventory, dynamic=result)

    assert not result.complete
    assert result.members == tuple(sorted(value.membership.members))
    assert {finding.boundary for finding in result.findings} == {"sentry-skill-catalogue"}
    assert "not complete" in result.findings[0].message
    assert {finding.kind for finding in drift.findings} == {"unresolved"}
    assert len(drift.discovered) == 8


def test_expired_complete_evidence_is_unresolved_and_never_authorizes_removal() -> None:
    value = declaration()
    value = replace(value, evidence=replace(value.evidence, expires="2026-01-01"))
    inventory = selected_inventory(value.boundary.target.source, value.boundary.target.binding)
    mandate = load(ROOT / "docs/evidence/agentkit/mandate.yaml")
    mandate = replace(
        mandate,
        tools=mandate.tools + (replace(mandate.tools[0], name="reviewed_but_absent"),),
    )

    result = reconcile(
        inventory,
        [value],
        source_bytes(value),
        selection=dict(value.selection),
        as_of=date(2027, 1, 1),
    )
    drift = compare(mandate, inventory, dynamic=result)

    assert not result.complete
    assert any("expired" in finding.message for finding in result.findings)
    assert not any(finding.kind == "removed" for finding in drift.findings)
    assert any(finding.tool == WITHHELD for finding in drift.findings)


def test_reconciliation_requires_an_actual_date() -> None:
    value = declaration()
    inventory = selected_inventory(value.boundary.target.source, value.boundary.target.binding)

    with pytest.raises(InventoryFormatError, match="as_of must be a date"):
        reconcile(
            inventory,
            [value],
            source_bytes(value),
            selection=dict(value.selection),
            as_of=datetime(2027, 1, 1),
        )


def reconcile_one(
    value: DynamicInventory,
    *,
    inventory: Inventory | None = None,
    contents: dict[str, bytes] | None = None,
    selection=None,
):
    return reconcile(
        inventory
        or selected_inventory(value.boundary.target.source, value.boundary.target.binding),
        [value],
        source_bytes(value) if contents is None else contents,
        selection=dict(value.selection) if selection is None else selection,
        as_of=date(2027, 1, 1),
    )


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("target", "target does not match"),
        ("selection", "selection does not match"),
        ("missing", "bytes were not supplied"),
        ("digest", "bytes do not match"),
        ("confidence", "evidence is not exact"),
        ("review", "evidence is not accepted"),
    ],
)
def test_each_ineligible_boundary_names_the_failed_condition(case: str, message: str) -> None:
    value = declaration()
    inventory = None
    contents = None
    selection = None
    if case == "target":
        inventory = selected_inventory("different.py", value.boundary.target.binding)
    elif case == "selection":
        selection = {"provider": ["different"]}
    elif case == "missing":
        contents = {}
    elif case == "digest":
        contents = {value.source.locator: b"tampered"}
    elif case == "confidence":
        value = replace(
            value, evidence=replace(value.evidence, confidence="heuristic")
        )
    else:
        value = replace(value, evidence=replace(value.evidence, review="contested"))

    result = reconcile_one(
        value, inventory=inventory, contents=contents, selection=selection
    )

    assert not result.complete
    assert any(message in finding.message for finding in result.findings)


def test_unreviewed_boundary_is_unaccepted_and_has_no_current_expiry() -> None:
    value = declaration()
    value = replace(
        value,
        evidence=replace(
            value.evidence, review="unreviewed", reviewer=None, expires=None
        ),
    )

    messages = [finding.message for finding in reconcile_one(value).findings]

    assert any("not accepted" in message for message in messages)
    assert any("expired" in message for message in messages)


def test_duplicate_and_disagreeing_boundary_claims_are_conflicts() -> None:
    value = declaration()
    inventory = selected_inventory(value.boundary.target.source, value.boundary.target.binding)

    duplicate = reconcile(
        inventory,
        [value, value],
        source_bytes(value),
        selection=dict(value.selection),
        as_of=date(2027, 1, 1),
    )
    changed = replace(
        value,
        source=replace(value.source, producer_version="0.7.5"),
        membership=replace(
            value.membership, members=value.membership.members + ("new_tool",)
        ),
    )
    disagreement = reconcile(
        inventory,
        [value, changed],
        source_bytes(value),
        selection=dict(value.selection),
        as_of=date(2027, 1, 1),
    )

    assert any("declared more than once" in item.message for item in duplicate.findings)
    assert any("disagree" in item.message for item in disagreement.findings)
    assert not duplicate.complete
    assert not disagreement.complete


def rehash(graph: AuthorityIR) -> AuthorityIR:
    digest = _inventory_semantic_sha256(graph.entities, graph.facts, graph.edges)
    return replace(
        graph,
        sources=(
            replace(graph.sources[0], semantic_sha256=digest),
            *graph.sources[1:],
        ),
    )


def replace_fact(graph: AuthorityIR, predicate: str, **changes) -> AuthorityIR:
    facts = tuple(
        replace(fact, **changes) if fact.predicate == predicate else fact
        for fact in graph.facts
    )
    return rehash(replace(graph, facts=facts))


def invalid_capture_digest(graph: AuthorityIR) -> AuthorityIR:
    digest = "A" * 64
    facts = tuple(
        replace(fact, value={**fact.value, "content_sha256": digest})
        if fact.predicate == "capture"
        else fact
        for fact in graph.facts
    )
    changed = replace(
        graph,
        sources=(graph.sources[0], replace(graph.sources[1], content_sha256=digest)),
        facts=facts,
    )
    return rehash(changed)


def mismatched_capture_fact(graph: AuthorityIR) -> AuthorityIR:
    facts = tuple(
        replace(fact, value={**fact.value, "producer_version": "other"})
        if fact.predicate == "capture"
        else fact
        for fact in graph.facts
    )
    return rehash(replace(graph, facts=facts))


def membership_without_capture_evidence(graph: AuthorityIR) -> AuthorityIR:
    declaration_source = graph.sources[0].id
    facts = tuple(
        replace(
            fact,
            evidence=tuple(
                item for item in fact.evidence if item.source == declaration_source
            ),
        )
        if fact.predicate == "members"
        else fact
        for fact in graph.facts
    )
    return rehash(replace(graph, facts=facts))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda graph: replace(graph, edges=graph.edges[:-1]),
            "structurally invalid",
        ),
        (
            lambda graph: replace(
                graph,
                sources=graph.sources
                + (replace(graph.sources[0], id="source:inventory:third"),),
            ),
            "exactly two sources",
        ),
        (
            lambda graph: replace(
                graph,
                sources=(replace(graph.sources[0], adapter="other"), graph.sources[1]),
            ),
            "unsupported sources",
        ),
        (
            lambda graph: replace(
                graph,
                sources=(replace(graph.sources[0], kind="other"), graph.sources[1]),
            ),
            "unsupported source",
        ),
        (
            lambda graph: replace(
                graph,
                entities=graph.entities
                + (Entity("scope:extra", "scope", "extra"),),
            ),
            "one boundary and only tool entities",
        ),
        (
            lambda graph: rehash(
                replace(
                    graph,
                    facts=graph.facts
                    + (
                        Fact(
                            "fact:boundary:agentkit-provider-tools:unknown",
                            "boundary:agentkit-provider-tools",
                            "unknown",
                            True,
                            graph.facts[0].evidence,
                        ),
                    ),
                )
            ),
            "unsupported predicate",
        ),
        (
            lambda graph: rehash(
                replace(
                    graph,
                    facts=tuple(
                        replace(fact, evidence=())
                        if fact.predicate == "expires"
                        else fact
                        for fact in graph.facts
                    ),
                )
            ),
            "unsupported evidence",
        ),
        (
            lambda graph: rehash(
                replace(
                    graph,
                    facts=tuple(
                        fact for fact in graph.facts if fact.predicate != "expires"
                    ),
                )
            ),
            "complete predicate set",
        ),
        (
            lambda graph: rehash(
                replace(
                    graph,
                    facts=tuple(
                        replace(
                            fact,
                            evidence=(
                                replace(fact.evidence[0], confidence="heuristic"),
                            ),
                        )
                        if fact.predicate == "expires"
                        else fact
                        for fact in graph.facts
                    ),
                )
            ),
            "disagree on evidence state",
        ),
        (
            lambda graph: replace_fact(graph, "name", value="wrong"),
            "name does not match entity",
        ),
        (
            lambda graph: replace_fact(
                graph, "target", value={"source": "../bad.py", "binding": "agent"}
            ),
            "safe relative POSIX path",
        ),
        (
            lambda graph: replace_fact(graph, "selection", value={"token": "bad"}),
            "unsupported key",
        ),
        (mismatched_capture_fact, "capture fact does not match"),
        (
            lambda graph: replace_fact(graph, "completeness", value="mostly"),
            "completeness has an invalid value",
        ),
        (
            invalid_capture_digest,
            "content_sha256 must be lowercase SHA-256",
        ),
        (membership_without_capture_evidence, "lacks captured-source evidence"),
        (
            lambda graph: replace(
                graph,
                sources=(
                    replace(graph.sources[0], semantic_sha256="0" * 64),
                    graph.sources[1],
                ),
            ),
            "semantic_sha256 does not match",
        ),
        (
            lambda graph: replace(
                graph,
                sources=(
                    graph.sources[0],
                    replace(graph.sources[1], semantic_sha256="0" * 64),
                ),
            ),
            "capture semantic_sha256 does not match members",
        ),
    ],
)
def test_inventory_profile_rejects_tampering(mutate, message: str) -> None:
    graph = mutate(declaration().to_ir())

    with pytest.raises(InventoryFormatError, match=message):
        _validate_inventory_profile(graph)


def test_inventory_profile_rejects_tool_name_and_member_set_mismatch() -> None:
    graph = declaration().to_ir()
    tool = next(entity for entity in graph.entities if entity.kind == "tool")
    facts = tuple(
        replace(fact, value="wrong")
        if fact.subject == tool.id and fact.predicate == "name"
        else fact
        for fact in graph.facts
    )
    with pytest.raises(InventoryFormatError, match="tool name does not match"):
        _validate_inventory_profile(rehash(replace(graph, facts=facts)))

    evidence = graph.facts[0].evidence
    extra = Entity("tool:extra", "tool", "extra")
    extra_fact = Fact("fact:tool:extra:name", "tool:extra", "name", "extra", evidence)
    widened = rehash(
        replace(graph, entities=graph.entities + (extra,), facts=graph.facts + (extra_fact,))
    )
    with pytest.raises(InventoryFormatError, match="members do not match tools"):
        _validate_inventory_profile(widened)
