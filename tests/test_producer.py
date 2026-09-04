from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

import agentmandate._producer as producer
from agentmandate import analyse, loads
from agentmandate._ir import (
    AuthorityIR,
    Entity,
    Fact,
    IRFormatError,
    _analyse_ir,
    _fact_id,
)
from agentmandate._producer import (
    AppliedProducerBoundary,
    ProducerBoundary,
    ProducerBoundaryFormatError,
    ProducerEvidence,
    ProducerResult,
    ProducerSelection,
    _captured,
    _digest,
    _integer,
    _load,
    _path,
    _pointer,
    _profile_digest,
    _record,
    _string,
    _strings,
    _validate_producer_profile,
    analyse_producers,
    migrate_aws_iam_access_key_boundary,
)

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "aws-iam-access-keys"
FIXTURE = ROOT / "tests" / "fixtures" / "producer-boundary-iam-v1.json"
RESULT_FIXTURES = ROOT / "tests" / "fixtures"


def _contents() -> dict[str, bytes]:
    return {
        str(path.relative_to(ROOT)): path.read_bytes()
        for path in (
            EVIDENCE / "catalogue.json",
            EVIDENCE / "capture.json",
            EVIDENCE / "capture.py",
        )
    }


def _raw() -> dict:
    return json.loads(FIXTURE.read_text())


def _mandate():
    path = EVIDENCE / "mandate.yaml"
    return loads(path.read_text(), source=str(path.relative_to(ROOT)))


def _reviewed(maximum: int = 2) -> ProducerBoundary:
    boundary = ProducerBoundary.from_json(FIXTURE.read_text())
    updated = replace(
        boundary,
        output=replace(
            boundary.output,
            capacity=replace(boundary.output.capacity, maximum=maximum),
        ),
        controls=replace(
            boundary.controls,
            accepted_through=replace(
                boundary.controls.accepted_through, count=maximum
            ),
            exhausted_at=replace(
                boundary.controls.exhausted_at, attempt=maximum + 1
            ),
        ),
        evidence=ProducerEvidence("exact", "accepted", "reviewer", "2026-12-31"),
    )
    return ProducerBoundary.from_json(updated.to_json())


def _selection(boundary: ProducerBoundary) -> ProducerSelection:
    return ProducerSelection(
        boundary.target.source,
        boundary.target.binding,
        boundary.target.producer,
        boundary.target.producer_version,
        boundary.partition.argument,
        boundary.partition.binding,
        boundary.output.scope,
    )


def _encoded(raw: object) -> str:
    return json.dumps(raw, separators=(",", ":"))


def _result_cases():
    mandate = _mandate()
    reviewed = _reviewed()
    maximum_three = _reviewed(3)
    unresolved = ProducerBoundary.from_json(
        replace(
            reviewed,
            evidence=ProducerEvidence("exact", "unreviewed", None, None),
        ).to_json()
    )
    return {
        "clean": analyse_producers(
            replace(
                mandate,
                limits=replace(mandate.limits, effects={"write": 4}),
            ),
            (),
            {},
            as_of=date(2026, 9, 3),
        ).to_result(),
        "bounded": analyse_producers(
            mandate,
            (reviewed,),
            _contents(),
            (_selection(reviewed),),
            as_of=date(2026, 9, 3),
        ).to_result(),
        "breached": analyse_producers(
            mandate,
            (maximum_three,),
            _contents(),
            (_selection(maximum_three),),
            as_of=date(2026, 9, 3),
        ).to_result(),
        "unresolved": analyse_producers(
            mandate,
            (unresolved,),
            _contents(),
            (_selection(unresolved),),
            as_of=date(2026, 9, 3),
        ).to_result(),
        "truncated": analyse_producers(
            mandate,
            (maximum_three,),
            _contents(),
            (_selection(maximum_three),),
            as_of=date(2026, 9, 3),
            depth=2,
        ).to_result(),
    }


def _rehash_result(raw: dict) -> str:
    body = {key: value for key, value in raw.items() if key != "result_sha256"}
    raw["result_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return _encoded(raw)


def test_canonical_migration_round_trips_and_verifies_caller_bytes() -> None:
    boundary = migrate_aws_iam_access_key_boundary(_contents())
    expected = FIXTURE.read_text()

    assert boundary.to_json() == expected
    assert ProducerBoundary.from_json(expected).to_json() == expected
    boundary.verify_sources(_contents())
    assert boundary.target.producer_version == "1.0.11"
    assert boundary.partition.argument == "user_name"
    assert boundary.output.capacity.kind == "concurrent"
    assert boundary.output.capacity.maximum == 2
    assert boundary.run_boundary.inventory == ("create_access_key",)
    assert boundary.run_boundary.release_tools == ()
    assert boundary.controls.accepted_through.count == 2
    assert boundary.controls.exhausted_at.attempt == 3
    assert boundary.evidence == ProducerEvidence("exact", "unreviewed", None, None)


def _rehash(graph: AuthorityIR) -> AuthorityIR:
    return replace(
        graph,
        sources=(
            replace(
                graph.sources[0],
                semantic_sha256=_profile_digest(
                    graph.entities, graph.facts, graph.edges
                ),
            ),
        ),
    )


def test_producer_boundary_projects_a_closed_standalone_ir_profile() -> None:
    boundary = ProducerBoundary.from_json(FIXTURE.read_text())
    graph = boundary.to_ir()

    assert AuthorityIR.from_json(graph.to_json()) == graph
    assert graph.sources[0].adapter == "agentmandate.producer-boundary"
    assert graph.sources[0].producer_version == "1.0.11"
    assert {entity.kind for entity in graph.entities} == {
        "producer_boundary",
        "resource_binding",
        "scope",
        "tool",
    }
    assert {edge.relation for edge in graph.edges} == {
        "bounds_output",
        "bounds_producer",
        "partitioned_by",
    }
    assert {fact.predicate for fact in graph.facts} >= {
        "capacity_kind",
        "capacity_maximum",
        "controls",
        "run_boundary",
        "sources",
    }


def test_generic_reachability_refuses_the_standalone_producer_profile() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()

    with pytest.raises(
        IRFormatError, match="sources do not match the analyzable manifest-v1 profile"
    ):
        _analyse_ir(graph)


def test_producer_profile_wraps_structural_ir_failures() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()
    broken = replace(graph, edges=(replace(graph.edges[0], support=()), *graph.edges[1:]))

    with pytest.raises(ProducerBoundaryFormatError, match="structurally invalid"):
        _validate_producer_profile(broken)

    facts = tuple(
        replace(fact, value={}) if fact.predicate == "output" else fact
        for fact in graph.facts
    )
    with pytest.raises(ProducerBoundaryFormatError, match="structurally invalid"):
        _validate_producer_profile(replace(graph, facts=facts))


def test_producer_profile_requires_one_supported_source() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()

    extra_source = replace(graph.sources[0], id="source:extra")
    with pytest.raises(ProducerBoundaryFormatError, match="exactly one source"):
        _validate_producer_profile(replace(graph, sources=(*graph.sources, extra_source)))
    with pytest.raises(ProducerBoundaryFormatError, match="unsupported source"):
        _validate_producer_profile(
            replace(graph, sources=(replace(graph.sources[0], kind="other"),))
        )


def test_producer_profile_rejects_unknown_entity_kind() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()
    extra = Entity("mystery:extra", "mystery", "extra")

    with pytest.raises(
        ProducerBoundaryFormatError, match="one boundary and three typed targets"
    ):
        _validate_producer_profile(replace(graph, entities=(*graph.entities, extra)))


def test_producer_profile_rejects_an_unknown_predicate() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()
    original = graph.facts[-1]
    changed = replace(
        original,
        id=original.id.rsplit(":", maxsplit=1)[0] + ":unknown",
        predicate="unknown",
    )

    with pytest.raises(ProducerBoundaryFormatError, match="unsupported predicate"):
        _validate_producer_profile(replace(graph, facts=(*graph.facts[:-1], changed)))


def test_producer_profile_rejects_unsupported_or_incomplete_fact_evidence() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()
    fact = graph.facts[0]
    unsupported = replace(fact, evidence=())

    with pytest.raises(ProducerBoundaryFormatError, match="unsupported evidence"):
        _validate_producer_profile(replace(graph, facts=(unsupported, *graph.facts[1:])))
    with pytest.raises(ProducerBoundaryFormatError, match="complete predicate set"):
        _validate_producer_profile(replace(graph, facts=graph.facts[1:]))


def test_producer_profile_requires_one_evidence_state() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()
    fact = graph.facts[0]
    changed = replace(
        fact,
        evidence=(replace(fact.evidence[0], confidence="heuristic"),),
    )

    with pytest.raises(ProducerBoundaryFormatError, match="disagree on evidence state"):
        _validate_producer_profile(_rehash(replace(graph, facts=(changed, *graph.facts[1:]))))


def test_producer_profile_must_reconstruct_the_strict_record() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()
    facts = tuple(
        replace(fact, value=0) if fact.predicate == "capacity_maximum" else fact
        for fact in graph.facts
    )

    with pytest.raises(ProducerBoundaryFormatError, match="reconstruct a valid record"):
        _validate_producer_profile(_rehash(replace(graph, facts=facts)))


def test_producer_profile_entities_and_identity_must_match_the_record() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()
    extra = Entity("scope:extra", "scope", "extra")
    extra_fact = Fact(
        _fact_id(extra.id, "name"),
        extra.id,
        "name",
        extra.name,
        graph.facts[0].evidence,
    )
    expanded = replace(
        graph,
        entities=(*graph.entities, extra),
        facts=(*graph.facts, extra_fact),
    )
    with pytest.raises(ProducerBoundaryFormatError, match="entities do not match"):
        _validate_producer_profile(_rehash(expanded))

    facts = tuple(
        replace(fact, value="different")
        if fact.predicate == "name" and fact.subject.startswith("producer_boundary:")
        else fact
        for fact in graph.facts
    )
    with pytest.raises(ProducerBoundaryFormatError, match="identity does not match"):
        _validate_producer_profile(_rehash(replace(graph, facts=facts)))


def test_producer_profile_relations_must_have_exact_support() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()
    edge = graph.edges[0]
    changed = replace(edge, support=(*edge.support, graph.facts[0].id))

    with pytest.raises(ProducerBoundaryFormatError, match="relations do not match"):
        _validate_producer_profile(_rehash(replace(graph, edges=(changed, *graph.edges[1:]))))


def test_producer_profile_fact_values_and_evidence_locations_are_closed() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()
    tool_name = next(
        fact
        for fact in graph.facts
        if fact.predicate == "name" and fact.subject.startswith("tool:")
    )
    changed_name = replace(tool_name, value="different")
    facts = tuple(changed_name if fact is tool_name else fact for fact in graph.facts)
    with pytest.raises(ProducerBoundaryFormatError, match="facts do not match"):
        _validate_producer_profile(_rehash(replace(graph, facts=facts)))

    first = graph.facts[0]
    changed_location = replace(
        first, evidence=(replace(first.evidence[0], location="/different"),)
    )
    facts = (changed_location, *graph.facts[1:])
    with pytest.raises(ProducerBoundaryFormatError, match="evidence locations"):
        _validate_producer_profile(_rehash(replace(graph, facts=facts)))


def test_producer_profile_checks_content_and_semantic_digests() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()

    with pytest.raises(ProducerBoundaryFormatError, match="content_sha256"):
        _validate_producer_profile(
            replace(graph, sources=(replace(graph.sources[0], content_sha256="0" * 64),))
        )
    with pytest.raises(ProducerBoundaryFormatError, match="semantic_sha256"):
        _validate_producer_profile(
            replace(graph, sources=(replace(graph.sources[0], semantic_sha256="0" * 64),))
        )


def test_producer_profile_checks_source_producer_version() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()

    with pytest.raises(ProducerBoundaryFormatError, match="identity does not match"):
        _validate_producer_profile(
            replace(graph, sources=(replace(graph.sources[0], producer_version="other"),))
        )


def test_producer_profile_checks_source_identity() -> None:
    graph = ProducerBoundary.from_json(FIXTURE.read_text()).to_ir()
    changed_source = replace(graph.sources[0], id="source:renamed")
    facts = tuple(
        replace(
            fact,
            evidence=(replace(fact.evidence[0], source=changed_source.id),),
        )
        for fact in graph.facts
    )
    changed_source = replace(
        changed_source,
        semantic_sha256=_profile_digest(graph.entities, facts, graph.edges),
    )

    with pytest.raises(ProducerBoundaryFormatError, match="source identity"):
        _validate_producer_profile(
            replace(graph, sources=(changed_source,), facts=facts)
        )


def test_private_analysis_applies_the_real_maximum_two_boundary() -> None:
    mandate = _mandate()
    boundary = _reviewed()
    baseline = analyse(mandate)

    result = analyse_producers(
        mandate,
        (boundary,),
        _contents(),
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
    )

    assert [breach.kind for breach in baseline.breaches] == ["effect_count"]
    assert len(baseline.breaches[0].path) == 3
    assert result.authority.breaches == ()
    assert result.findings == ()
    assert result.applied == (
        AppliedProducerBoundary(
            boundary.id,
            "create_access_key",
            "access_key",
            "reviewed-iam-user",
            "concurrent",
            2,
            result.applied[0].support,
        ),
    )
    assert set(result.applied[0].support) >= {
        boundary.to_ir().sources[0].id,
        *[edge.id for edge in boundary.to_ir().edges],
        "fact:tool:create_access_key:produces",
        "fact:tool:create_access_key:unbounded",
    }
    assert result.as_of == "2026-09-03"

    one_call_budget = replace(
        mandate, limits=replace(mandate.limits, effects={"write": 1})
    )
    two_step = analyse_producers(
        one_call_budget,
        (boundary,),
        _contents(),
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
    )
    assert len(two_step.authority.breaches[0].path) == 2


@pytest.mark.parametrize(
    ("maximum", "breach_length"),
    [(1, None), (3, 3)],
)
def test_private_analysis_synthetic_maximum_controls(
    maximum: int, breach_length: int | None
) -> None:
    mandate = _mandate()
    boundary = _reviewed(maximum)

    result = analyse_producers(
        mandate,
        (boundary,),
        _contents(),
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
    )

    assert result.applied[0].maximum == maximum
    if breach_length is None:
        assert result.authority.breaches == ()
    else:
        assert len(result.authority.breaches[0].path) == breach_length


def test_no_producer_records_preserve_existing_authority() -> None:
    mandate = _mandate()

    result = analyse_producers(
        mandate,
        (),
        {},
        as_of=date(2026, 9, 3),
    )

    assert result.authority.as_dict() == analyse(mandate).as_dict()
    assert result.findings == ()
    assert result.applied == ()


@pytest.mark.parametrize(
    ("as_of", "message"),
    [
        (datetime(2026, 9, 3), "as_of must be a date"),
        ("2026-09-03", "as_of must be a date"),
    ],
)
def test_producer_analysis_requires_a_caller_date(as_of, message: str) -> None:
    with pytest.raises(ProducerBoundaryFormatError, match=message):
        analyse_producers(_mandate(), (), {}, as_of=as_of)  # type: ignore[arg-type]


def test_producer_analysis_validates_selection_and_source_input_types() -> None:
    with pytest.raises(ProducerBoundaryFormatError, match="ProducerSelection"):
        analyse_producers(
            _mandate(), (), {}, "selection", as_of=date(2026, 9, 3)  # type: ignore[arg-type]
        )
    with pytest.raises(ProducerBoundaryFormatError, match="map locators to bytes"):
        analyse_producers(
            _mandate(), (), {"source": "text"}, as_of=date(2026, 9, 3)  # type: ignore[dict-item]
        )


def test_missing_selection_retains_the_manifest_result() -> None:
    mandate = _mandate()
    boundary = _reviewed()

    result = analyse_producers(
        mandate, (boundary,), _contents(), as_of=date(2026, 9, 3)
    )

    assert result.authority.as_dict() == analyse(mandate).as_dict()
    assert [finding.message for finding in result.findings] == [
        "producer boundary lacks one exact selected deployment and partition"
    ]


def test_selection_mismatch_is_a_finding_not_a_smaller_graph() -> None:
    mandate = _mandate()
    boundary = _reviewed()
    selection = replace(_selection(boundary), producer_version="different")

    result = analyse_producers(
        mandate,
        (boundary,),
        _contents(),
        (selection,),
        as_of=date(2026, 9, 3),
    )

    assert result.authority.as_dict() == analyse(mandate).as_dict()
    assert "selected deployment and partition" in result.findings[0].message


def test_absent_or_ineligible_manifest_producer_retains_authority() -> None:
    mandate = _mandate()
    boundary = _reviewed()
    absent = replace(mandate, tools=())
    absent_result = analyse_producers(
        absent,
        (boundary,),
        _contents(),
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
    )
    assert absent_result.findings[0].message == (
        "producer target tool is not present in the mandate"
    )

    bounded_tool = replace(mandate.tools[0], unbounded=False)
    bounded = replace(mandate, tools=(bounded_tool,))
    bounded_result = analyse_producers(
        bounded,
        (boundary,),
        _contents(),
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
    )
    assert bounded_result.findings[0].message == (
        "producer target is not an unbounded mandate producer of the selected scope"
    )


@pytest.mark.parametrize(
    ("run_change", "message"),
    [
        (
            {"inventory_completeness": "partial"},
            "selected inventory is not complete",
        ),
        (
            {"release_completeness": "partial"},
            "release classification is not complete",
        ),
        (
            {"release_tools": ("create_access_key",)},
            "reachable release transition",
        ),
    ],
)
def test_incomplete_or_non_monotone_run_boundaries_do_not_narrow(
    run_change: dict, message: str
) -> None:
    mandate = _mandate()
    boundary = _reviewed()
    changed = ProducerBoundary.from_json(
        replace(
            boundary,
            run_boundary=replace(boundary.run_boundary, **run_change),
        ).to_json()
    )

    result = analyse_producers(
        mandate,
        (changed,),
        _contents(),
        (_selection(changed),),
        as_of=date(2026, 9, 3),
    )

    assert result.authority.as_dict() == analyse(mandate).as_dict()
    assert any(message in finding.message for finding in result.findings)


def test_another_reachable_producer_of_the_scope_blocks_narrowing() -> None:
    mandate = _mandate()
    boundary = _reviewed()
    competitor = replace(mandate.tools[0], name="other_producer")
    expanded = replace(mandate, tools=(*mandate.tools, competitor))

    result = analyse_producers(
        expanded,
        (boundary,),
        _contents(),
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
    )

    assert any("another reachable producer" in item.message for item in result.findings)
    assert result.applied == ()


def test_distinct_selected_boundaries_can_bound_distinct_producers() -> None:
    mandate = _mandate()
    first = _reviewed(1)
    second = ProducerBoundary.from_json(
        replace(
            first,
            id="producer-boundaries/other-key",
            target=replace(first.target, binding="other_producer"),
            output=replace(first.output, scope="other_key"),
            run_boundary=replace(
                first.run_boundary, inventory=("other_producer",)
            ),
        ).to_json()
    )
    other_tool = replace(
        mandate.tools[0], name="other_producer", produces="other_key"
    )
    expanded = replace(mandate, tools=(*mandate.tools, other_tool))

    result = analyse_producers(
        expanded,
        (first, second),
        _contents(),
        (_selection(first), _selection(second)),
        as_of=date(2026, 9, 3),
    )

    assert result.findings == ()
    assert [item.tool for item in result.applied] == [
        "create_access_key",
        "other_producer",
    ]


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        (
            ProducerEvidence("heuristic", "accepted", "reviewer", "2026-12-31"),
            "not exact and accepted",
        ),
        (
            ProducerEvidence("exact", "contested", "reviewer", "2026-12-31"),
            "not exact and accepted",
        ),
        (
            ProducerEvidence("exact", "accepted", "reviewer", "2026-09-02"),
            "missing accountability or expired",
        ),
    ],
)
def test_untrusted_or_expired_evidence_retains_authority(
    evidence: ProducerEvidence, message: str
) -> None:
    mandate = _mandate()
    boundary = _reviewed()
    changed = ProducerBoundary.from_json(replace(boundary, evidence=evidence).to_json())

    result = analyse_producers(
        mandate,
        (changed,),
        _contents(),
        (_selection(changed),),
        as_of=date(2026, 9, 3),
    )

    assert result.authority.as_dict() == analyse(mandate).as_dict()
    assert any(message in finding.message for finding in result.findings)


def test_unreviewed_migration_remains_ineligible() -> None:
    mandate = _mandate()
    boundary = migrate_aws_iam_access_key_boundary(_contents())

    result = analyse_producers(
        mandate,
        (boundary,),
        _contents(),
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
    )

    assert result.applied == ()
    assert {item.message for item in result.findings} == {
        "producer evidence is not exact and accepted",
        "producer review is missing accountability or expired",
    }


def test_missing_or_changed_source_bytes_are_findings() -> None:
    mandate = _mandate()
    boundary = _reviewed()
    contents = _contents()
    contents.pop(next(iter(contents)))

    missing = analyse_producers(
        mandate,
        (boundary,),
        contents,
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
    )
    assert missing.findings[0].message == "producer source bytes failed verification"

    contents = _contents()
    contents[next(iter(contents))] = b"changed"
    changed = analyse_producers(
        mandate,
        (boundary,),
        contents,
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
    )
    assert changed.findings[0].message == "producer source bytes failed verification"


def test_duplicate_and_competing_boundaries_block_every_narrowing() -> None:
    mandate = _mandate()
    boundary = _reviewed()

    result = analyse_producers(
        mandate,
        (boundary, boundary),
        _contents(),
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
    )

    assert result.applied == ()
    assert {item.message for item in result.findings} == {
        "producer boundary id is declared more than once",
        "multiple producer boundaries target the same tool",
    }
    assert ProducerResult.from_json(result.to_result().to_json()) == result.to_result()

    duplicate_selection = analyse_producers(
        mandate,
        (boundary,),
        _contents(),
        (_selection(boundary), _selection(boundary)),
        as_of=date(2026, 9, 3),
    )
    assert duplicate_selection.findings[0].code == "producer.selection-unresolved"
    assert ProducerResult.from_json(
        duplicate_selection.to_result().to_json()
    ) == duplicate_selection.to_result()


def test_depth_is_forwarded_to_the_private_search() -> None:
    mandate = _mandate()
    boundary = _reviewed(3)

    result = analyse_producers(
        mandate,
        (boundary,),
        _contents(),
        (_selection(boundary),),
        as_of=date(2026, 9, 3),
        depth=2,
    )

    assert result.authority.depth == 2
    assert result.authority.breaches == ()


@pytest.mark.parametrize("case", ["clean", "bounded", "breached", "unresolved", "truncated"])
def test_producer_result_v1_canonical_fixtures(case: str) -> None:
    result = _result_cases()[case]
    expected = (RESULT_FIXTURES / f"producer-result-v1-{case}.json").read_text()

    assert result.to_json() == expected
    assert ProducerResult.from_json(expected) == result
    assert ProducerResult.from_json(expected).to_json() == expected


def test_producer_result_records_inputs_codes_and_capacity_semantics() -> None:
    cases = _result_cases()
    bounded = cases["bounded"].as_dict()
    unresolved = cases["unresolved"].as_dict()

    assert bounded["schema"] == "agentmandate.producers/v1"
    assert bounded["result_version"] == 1
    assert bounded["inputs"]["manifest"]["locator"].endswith("mandate.yaml")
    assert len(bounded["inputs"]["boundaries"]) == 1
    assert bounded["applied"][0]["capacity_kind"] == "concurrent"
    assert bounded["applied"][0]["maximum"] == 2
    assert {item["code"] for item in unresolved["findings"]} == {
        "producer.evidence-untrusted",
        "producer.review-unresolved",
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{", "not valid JSON"),
        ('{"value":NaN}', "non-canonical value"),
        ("[]", "must be an object"),
        ('{"result_sha256":"' + "0" * 64 + '"}', "missing field"),
    ],
)
def test_producer_result_rejects_malformed_outer_envelopes(text: str, message: str) -> None:
    with pytest.raises(ProducerBoundaryFormatError, match=message):
        ProducerResult.from_json(text)


def test_producer_result_rejects_unknown_outer_fields_and_bad_checksums() -> None:
    raw = _result_cases()["bounded"].as_dict()
    raw["unknown"] = True
    with pytest.raises(ProducerBoundaryFormatError, match="unknown field"):
        ProducerResult.from_json(_encoded(raw))

    raw = _result_cases()["bounded"].as_dict()
    raw["result_sha256"] = "not-a-digest"
    with pytest.raises(ProducerBoundaryFormatError, match="lowercase SHA-256"):
        ProducerResult.from_json(_encoded(raw))

    raw = _result_cases()["bounded"].as_dict()
    raw["as_of"] = "2026-09-04"
    with pytest.raises(ProducerBoundaryFormatError, match="SHA-256 does not match"):
        ProducerResult.from_json(_encoded(raw))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(result_version=True), "unsupported producer result version"),
        (lambda raw: raw.update(schema="other/v1"), "unsupported producer result schema"),
        (lambda raw: raw.update(as_of="2026-02-30"), "canonical calendar date"),
        (lambda raw: raw.update(as_of="September"), "canonical calendar date"),
        (lambda raw: raw["inputs"].update(extra=True), "unknown field"),
        (lambda raw: raw["inputs"].update(manifest=[]), "must be an object"),
        (
            lambda raw: raw["inputs"]["manifest"].update(semantic_sha256="A" * 64),
            "lowercase SHA-256",
        ),
        (lambda raw: raw["inputs"].update(boundaries={}), "must be an array"),
        (
            lambda raw: raw["inputs"].update(
                boundaries=[
                    raw["inputs"]["boundaries"][0],
                    {
                        **raw["inputs"]["boundaries"][0],
                        "id": "a-boundary",
                    },
                ]
            ),
            "boundaries must be sorted",
        ),
        (lambda raw: raw["inputs"].update(selections={}), "must be an array"),
        (
            lambda raw: raw["inputs"].update(
                selections=[
                    raw["inputs"]["selections"][0],
                    {
                        **raw["inputs"]["selections"][0],
                        "source": "a.py",
                    },
                ]
            ),
            "selections must be sorted",
        ),
        (
            lambda raw: raw["inputs"]["selections"][0].update(
                partition_binding="secret"
            ),
            "reviewed non-secret alias",
        ),
        (lambda raw: raw.update(authority=[]), "must be an object"),
        (lambda raw: raw["authority"].pop("depth"), "missing field"),
        (lambda raw: raw["authority"].update(extra=True), "unknown field"),
        (
            lambda raw: raw["authority"].update(reachable_tools={}),
            "must be an array",
        ),
        (
            lambda raw: raw["authority"].update(reachable_tools=["z", "a"]),
            "sorted unique strings",
        ),
        (lambda raw: raw["authority"].update(effects=["write"]), "string pairs"),
        (
            lambda raw: raw["authority"].update(effects=[["z", "a"], ["a", "z"]]),
            "sorted and unique",
        ),
        (
            lambda raw: raw["authority"].update(
                max_extractable={"amount": "not-decimal", "currency": "USD"}
            ),
            "must be decimal",
        ),
        (
            lambda raw: raw["authority"].update(
                max_extractable={"amount": "NaN", "currency": "USD"}
            ),
            "must be canonical",
        ),
        (
            lambda raw: raw["authority"].update(
                max_extractable={"amount": "1", "currency": " "}
            ),
            "non-empty trimmed string",
        ),
        (lambda raw: raw["authority"].update(breaches={}), "must be an array"),
        (
            lambda raw: raw["authority"].update(
                breaches=[{"kind": "effect", "detail": "detail", "path": []}]
            ),
            "non-empty array",
        ),
        (lambda raw: raw["authority"].update(depth=True), "non-negative integer"),
        (lambda raw: raw["authority"].update(truncated=0), "must be a boolean"),
        (lambda raw: raw.update(applied={}), "/applied must be an array"),
        (
            lambda raw: raw["applied"][0].update(boundary=" "),
            "non-empty trimmed string",
        ),
        (lambda raw: raw["applied"][0].update(support={}), "must be an array"),
        (
            lambda raw: raw["applied"][0].update(support=["z", "a"]),
            "sorted unique strings",
        ),
        (
            lambda raw: raw["applied"][0].update(capacity_kind="lifetime"),
            "capacity_kind is unsupported",
        ),
        (
            lambda raw: raw["applied"][0].update(maximum=0),
            "maximum must be a positive integer",
        ),
        (
            lambda raw: raw.update(applied=raw["applied"] * 2),
            "sorted unique boundary ids",
        ),
        (lambda raw: raw.update(findings={}), "/findings must be an array"),
        (
            lambda raw: raw["findings"][0].update(code="producer.unknown"),
            "code is unsupported",
        ),
    ],
)
def test_producer_result_strictly_validates_inner_contract(mutate, message: str) -> None:
    case = "unresolved" if message == "code is unsupported" else "bounded"
    raw = _result_cases()[case].as_dict()
    mutate(raw)

    with pytest.raises(ProducerBoundaryFormatError, match=message):
        ProducerResult.from_json(_rehash_result(raw))


def test_producer_result_rejects_noncanonical_programmatic_values() -> None:
    with pytest.raises(ProducerBoundaryFormatError, match="non-canonical value"):
        producer._canonical_bytes(float("nan"))
    with pytest.raises(ProducerBoundaryFormatError, match="non-canonical value"):
        producer._canonical_bytes(object())


def test_reader_canonicalizes_set_like_collections() -> None:
    raw = _raw()
    raw["sources"].reverse()
    raw["run_boundary"]["inventory"] = ["z", "create_access_key"]
    raw["run_boundary"]["release_tools"] = ["release-z", "release-a"]

    rendered = ProducerBoundary.from_json(_encoded(raw)).as_dict()

    assert [source["id"] for source in rendered["sources"]] == sorted(
        source["id"] for source in raw["sources"]
    )
    assert rendered["run_boundary"]["inventory"] == ["create_access_key", "z"]
    assert rendered["run_boundary"]["release_tools"] == ["release-a", "release-z"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{", "not valid JSON at line 1 column 2"),
        ("NaN", "non-canonical value"),
        ("[]", "root must be an object"),
        ("{}", "missing field 'producer_boundary_version'"),
        (None, "non-canonical value"),
    ],
)
def test_invalid_roots_have_one_typed_error_boundary(text, message: str) -> None:
    with pytest.raises(ProducerBoundaryFormatError, match=message):
        ProducerBoundary.from_json(text)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(producer_boundary_version=True), "version type"),
        (lambda raw: raw.update(producer_boundary_version=2), "version 2"),
        (lambda raw: raw.update(extra="secret-value"), "unknown field 'extra'"),
        (lambda raw: raw.pop("id"), "missing field 'id'"),
        (lambda raw: raw.update(id=" padded "), "non-empty stripped string"),
        (lambda raw: raw.update(adapter=[]), "adapter must be an object"),
        (lambda raw: raw["adapter"].update(name="other"), "adapter is not supported"),
        (lambda raw: raw["adapter"].update(version=2), "adapter is not supported"),
        (lambda raw: raw["target"].update(source="/tmp/source"), "relative POSIX path"),
        (lambda raw: raw["target"].update(source="a\\b"), "relative POSIX path"),
        (lambda raw: raw["target"].update(source="a/../b"), "relative POSIX path"),
        (lambda raw: raw["partition"].update(argument=""), "non-empty stripped string"),
        (
            lambda raw: raw["partition"].update(binding="actual-user-name"),
            "reviewed non-secret alias",
        ),
        (lambda raw: raw["output"].update(capacity=[]), "capacity must be an object"),
        (lambda raw: raw["output"]["capacity"].update(kind="cumulative"), "not supported"),
        (lambda raw: raw["output"]["capacity"].update(maximum=0), "at least 1"),
        (lambda raw: raw["output"]["capacity"].update(maximum=True), "at least 1"),
        (lambda raw: raw["run_boundary"].update(inventory=[]), "non-empty array"),
        (lambda raw: raw["run_boundary"].update(release_tools="none"), "possibly empty array"),
        (
            lambda raw: raw["run_boundary"].update(inventory=["tool", "tool"]),
            "contains duplicates",
        ),
        (
            lambda raw: raw["run_boundary"].update(inventory_completeness="mostly"),
            "invalid value",
        ),
        (
            lambda raw: raw["controls"]["accepted_through"].update(source="source:missing"),
            "unknown source",
        ),
        (
            lambda raw: raw["controls"]["accepted_through"].update(
                source="source:upstream-inventory"
            ),
            "must cite capacity-control evidence",
        ),
        (
            lambda raw: raw["controls"]["exhausted_at"].update(reason="rate_limited"),
            "not supported",
        ),
        (
            lambda raw: raw["controls"]["accepted_through"].update(location="outcomes/1"),
            "absolute JSON Pointer",
        ),
        (
            lambda raw: raw["controls"]["accepted_through"].update(count=1),
            "must equal capacity maximum",
        ),
        (
            lambda raw: raw["controls"]["exhausted_at"].update(attempt=4),
            "must follow capacity maximum",
        ),
        (lambda raw: raw.update(sources=[]), "non-empty array"),
        (lambda raw: raw["sources"].pop(), "cover every required role"),
        (lambda raw: raw["sources"][0].update(role="other"), "role is not supported"),
        (
            lambda raw: raw["sources"][0].update(kind="other"),
            "kind does not match its role",
        ),
        (
            lambda raw: raw["sources"][1].update(id=raw["sources"][0]["id"]),
            "duplicate identities",
        ),
        (
            lambda raw: raw["sources"][1].update(locator=raw["sources"][0]["locator"]),
            "duplicate identities",
        ),
        (
            lambda raw: raw["sources"][1].update(
                role=raw["sources"][0]["role"], kind=raw["sources"][0]["kind"]
            ),
            "duplicate identities",
        ),
        (lambda raw: raw["sources"][0].update(content_sha256="A" * 64), "lowercase SHA-256"),
        (lambda raw: raw["evidence"].update(confidence="certain"), "state is invalid"),
        (lambda raw: raw["evidence"].update(review="pending"), "state is invalid"),
        (
            lambda raw: raw["target"].update(source="docs/other.py"),
            "does not match the selected run boundary",
        ),
        (
            lambda raw: raw["run_boundary"].update(inventory=["other"]),
            "does not match the selected run boundary",
        ),
        (
            lambda raw: raw["evidence"].update(reviewer="reviewer", expires="2027-01-01"),
            "cannot carry accountability",
        ),
        (
            lambda raw: raw["evidence"].update(
                review="accepted", reviewer="reviewer", expires="20270101"
            ),
            "canonical ISO date",
        ),
        (
            lambda raw: raw["evidence"].update(
                review="accepted", reviewer="reviewer", expires="2027-02-30"
            ),
            "real calendar date",
        ),
    ],
)
def test_invalid_shapes_are_typed_and_value_safe(mutate, message: str) -> None:
    raw = _raw()
    mutate(raw)

    with pytest.raises(ProducerBoundaryFormatError, match=message) as caught:
        ProducerBoundary.from_json(_encoded(raw))

    assert "secret-value" not in str(caught.value)


def test_reviewed_evidence_requires_accountability_and_accepts_real_dates() -> None:
    raw = _raw()
    raw["evidence"] = {
        "confidence": "exact",
        "review": "accepted",
        "reviewer": "security-platform",
        "expires": "2027-08-29",
    }
    assert ProducerBoundary.from_json(_encoded(raw)).evidence == ProducerEvidence(
        "exact", "accepted", "security-platform", "2027-08-29"
    )

    raw["evidence"]["reviewer"] = None
    with pytest.raises(ProducerBoundaryFormatError, match="non-empty stripped string"):
        ProducerBoundary.from_json(_encoded(raw))


def test_source_verification_rejects_bad_shape_set_and_digest() -> None:
    boundary = ProducerBoundary.from_json(FIXTURE.read_text())

    with pytest.raises(ProducerBoundaryFormatError, match="locator-to-bytes"):
        boundary.verify_sources({"source": "not-bytes"})  # type: ignore[dict-item]
    with pytest.raises(ProducerBoundaryFormatError, match="source set differs"):
        boundary.verify_sources({})
    with pytest.raises(ProducerBoundaryFormatError, match="source set differs") as caught:
        boundary.verify_sources({**_contents(), "secret-locator": b"secret"})
    assert "secret-locator" not in str(caught.value)
    changed = _contents()
    changed[next(iter(changed))] = b"changed"
    with pytest.raises(ProducerBoundaryFormatError, match="source bytes do not match"):
        boundary.verify_sources(changed)


def test_private_helpers_reject_unsafe_values() -> None:
    assert _record({"field": 1}, "test", {"field"}) == {"field": 1}
    assert _string("value", "test") == "value"
    assert _integer(0, "test", minimum=0) == 0
    assert _digest("0" * 64, "test") == "0" * 64
    assert _path("path/file", "test") == "path/file"
    assert _pointer("/value", "test") == "/value"
    assert _strings([], "test", allow_empty=True) == ()
    assert _load("{}", "test") == {}

    with pytest.raises(ProducerBoundaryFormatError, match="must be an object"):
        _record([], "test", set())
    with pytest.raises(ProducerBoundaryFormatError, match="non-empty stripped string"):
        _string(1, "test")


def _rehashed(monkeypatch, contents: dict[str, bytes]) -> None:
    sources = deepcopy(producer._IAM_SOURCES)
    for locator, (kind, role, _digest_value) in sources.items():
        sources[locator] = (kind, role, hashlib.sha256(contents[locator]).hexdigest())
    monkeypatch.setattr(producer, "_IAM_SOURCES", sources)


def _replace_json(
    contents: dict[str, bytes], suffix: str, mutate
) -> dict[str, bytes]:
    changed = dict(contents)
    locator = next(path for path in changed if path.endswith(suffix))
    raw = json.loads(changed[locator])
    mutate(raw)
    changed[locator] = json.dumps(raw).encode()
    return changed


def test_migration_rejects_source_set_type_and_digest() -> None:
    with pytest.raises(ProducerBoundaryFormatError, match="source set differs"):
        migrate_aws_iam_access_key_boundary({})
    with pytest.raises(ProducerBoundaryFormatError, match="locator-to-bytes"):
        migrate_aws_iam_access_key_boundary([])  # type: ignore[arg-type]
    with pytest.raises(ProducerBoundaryFormatError, match="locator-to-bytes"):
        migrate_aws_iam_access_key_boundary({1: b"value"})  # type: ignore[dict-item]
    with pytest.raises(ProducerBoundaryFormatError, match="source set differs") as caught:
        migrate_aws_iam_access_key_boundary({**_contents(), "secret-locator": b"secret"})
    assert "secret-locator" not in str(caught.value)

    contents = _contents()
    locator = next(iter(contents))
    contents[locator] = b"changed"
    with pytest.raises(ProducerBoundaryFormatError, match="reviewed locator"):
        migrate_aws_iam_access_key_boundary(contents)

    contents = _contents()
    contents[locator] = "not-bytes"  # type: ignore[assignment]
    with pytest.raises(ProducerBoundaryFormatError, match="must be bytes"):
        migrate_aws_iam_access_key_boundary(contents)


@pytest.mark.parametrize(
    ("suffix", "mutate", "message"),
    [
        ("catalogue.json", lambda raw: raw.update(tools={}), "tools must be an array"),
        ("catalogue.json", lambda raw: raw["tools"].pop(), "selected producer"),
        ("capture.json", lambda raw: raw.update(capture_version=2), "controls do not match"),
        ("capture.json", lambda raw: raw["outcomes"].pop(), "controls do not match"),
    ],
)
def test_migration_rejects_changed_controls(suffix, mutate, message, monkeypatch) -> None:
    contents = _replace_json(_contents(), suffix, mutate)
    _rehashed(monkeypatch, contents)

    with pytest.raises(ProducerBoundaryFormatError, match=message):
        migrate_aws_iam_access_key_boundary(contents)


def test_migration_capture_requires_an_object(monkeypatch) -> None:
    contents = _contents()
    locator = next(path for path in contents if path.endswith("catalogue.json"))
    contents[locator] = b"[]"
    _rehashed(monkeypatch, contents)

    with pytest.raises(ProducerBoundaryFormatError, match="must contain an object"):
        _captured(contents, locator)

    contents[locator] = b"\xff"
    with pytest.raises(ProducerBoundaryFormatError, match="is not UTF-8"):
        _captured(contents, locator)


def test_migration_catalogue_schema_is_typed(monkeypatch) -> None:
    contents = _replace_json(
        _contents(),
        "catalogue.json",
        lambda raw: raw["tools"][0].update(
            name="create_access_key", inputSchema=[], outputSchema=[]
        ),
    )
    _rehashed(monkeypatch, contents)

    with pytest.raises(ProducerBoundaryFormatError, match="selected producer"):
        migrate_aws_iam_access_key_boundary(contents)


def test_dataclass_replacement_stays_immutable() -> None:
    boundary = ProducerBoundary.from_json(FIXTURE.read_text())
    changed = replace(boundary, id="other")

    assert boundary.id == "producer-boundaries/iam-user-access-keys"
    assert changed.id == "other"
