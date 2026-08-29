from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agentmandate._cedar import (
    CedarBundle,
    CedarBundleFormatError,
    _profile_digest,
    _validate_cedar_profile,
)
from agentmandate._ir import (
    AuthorityIR,
    Entity,
    Evidence,
    IRFormatError,
    _analyse_ir,
    _entity_id,
    _fact_id,
)

ROOT = Path(__file__).parents[1] / "docs" / "evidence" / "cedar-document-cloud"
BUNDLE = ROOT / "bundle.json"
SCHEMA_CHECKED = Path(__file__).parents[1] / "probes" / "cedar-schema-checked"


def raw_bundle() -> dict[str, Any]:
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


def text(raw: Any) -> str:
    return json.dumps(raw)


def set_path(raw: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    target: Any = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


def with_mapping() -> dict[str, Any]:
    raw = raw_bundle()
    content = b"reviewed deployment mapping"
    raw["sources"].append(
        {
            "kind": "deployment_mapping",
            "locator": "mapping.json",
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "origin": None,
            "origin_revision": None,
        }
    )
    raw["mapping"] = {
        "mapping_version": 1,
        "source": "mapping.json",
        "target": {"source": "examples/agent.yaml", "agent": "document-agent"},
        "principal": {"cedar_types": ["Workload"], "mandate_principal": "caller"},
        "actions": [
            {"cedar": 'Action::"ViewDocument"', "tool": "view_document"},
            {"cedar": 'Action::"CreateDocument"', "tool": "create_document"},
        ],
        "resources": [
            {"cedar_type": "Drive", "binding": "document-cloud"},
            {"cedar_type": "Document", "binding": "document-cloud"},
        ],
        "request_domain": {
            "completeness": "complete",
            "evidence": {
                "confidence": "exact",
                "review": "accepted",
                "reviewer": "platform-security",
                "expires": "2027-08-29",
            },
        },
    }
    return raw


def test_the_official_bundle_is_canonical_and_digest_bound() -> None:
    bundle = CedarBundle.from_json(BUNDLE.read_text(encoding="utf-8"))

    assert bundle.bundle_version == 1
    assert bundle.cedar.language_version == "4.5"
    assert bundle.cedar.sdk_version == "4.12.0"
    assert bundle.adapter.name == "agentmandate.cedar-capture"
    assert bundle.validation.status == "success"
    assert [(item.id, item.decision) for item in bundle.decisions] == [
        ("alice-view-alice-public", "allow"),
        ("bob-view-alice-public", "deny"),
    ]
    assert all(not item.schema_checked for item in bundle.decisions)
    assert bundle.mapping is None
    native = json.loads((ROOT / "native-output.json").read_text(encoding="utf-8"))
    assert native["validation"]["type"] == "success"
    assert native["schema_checked_probe"]["type"] == "failure"
    assert "expected to have type `DocumentShare`" in native["schema_checked_probe"]["errors"][0][
        "message"
    ]
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    package = lock["packages"]["node_modules/@cedar-policy/cedar-wasm"]
    assert package["version"] == bundle.cedar.implementation_version
    assert package["integrity"] == bundle.cedar.package_integrity
    assert BUNDLE.read_text(encoding="utf-8") == bundle.to_json()
    assert CedarBundle.from_json(bundle.to_json()) == bundle
    bundle.verify_sources(
        {source.locator: (ROOT / source.locator).read_bytes() for source in bundle.sources}
    )


def rehash(graph: AuthorityIR) -> AuthorityIR:
    source = replace(
        graph.sources[0],
        semantic_sha256=_profile_digest(graph.entities, graph.facts, graph.edges),
    )
    return replace(graph, sources=(source,))


def test_official_bundle_projects_observed_policy_decisions_without_claiming_completeness() -> None:
    bundle = CedarBundle.from_json(BUNDLE.read_text(encoding="utf-8"))
    graph = bundle.to_ir()

    assert len(graph.entities) == 8
    assert len(graph.facts) == 32
    assert len(graph.edges) == 5
    assert {edge.relation for edge in graph.edges} == {
        "contains_policy",
        "decides_request",
    }
    facts = {(fact.subject, fact.predicate): fact.value for fact in graph.facts}
    policy_set = next(entity for entity in graph.entities if entity.kind == "policy_set")
    assert facts[(policy_set.id, "policy_inventory_complete")] is False
    assert {
        entity.name for entity in graph.entities if entity.kind == "policy"
    } == {"policy1", "policy4", "policy9"}
    assert {
        facts[(entity.id, "schema_checked")]
        for entity in graph.entities
        if entity.kind == "decision"
    } == {False}
    assert AuthorityIR.from_json(graph.to_json()).to_json() == graph.to_json()
    _validate_cedar_profile(AuthorityIR.from_json(graph.to_json()))
    with pytest.raises(IRFormatError, match="analyzable manifest-v1 profile"):
        _analyse_ir(graph, depth=8)


def test_synthetic_probe_covers_schema_checked_decisions_without_mapping() -> None:
    bundle = CedarBundle.from_json(
        (SCHEMA_CHECKED / "bundle.json").read_text(encoding="utf-8")
    )
    bundle.verify_sources(
        {
            source.locator: (SCHEMA_CHECKED / source.locator).read_bytes()
            for source in bundle.sources
        }
    )
    graph = bundle.to_ir()
    decision_facts = {
        (fact.subject, fact.predicate): fact.value for fact in graph.facts
    }

    assert bundle.mapping is None
    assert {decision.decision for decision in bundle.decisions} == {"allow", "deny"}
    assert all(decision.schema_checked for decision in bundle.decisions)
    assert {
        decision_facts[(entity.id, "schema_checked")]
        for entity in graph.entities
        if entity.kind == "decision"
    } == {True}


def test_synthetic_schema_checked_capture_is_byte_exact_when_installed() -> None:
    package = SCHEMA_CHECKED / "node_modules" / "@cedar-policy" / "cedar-wasm"
    if not package.is_dir():
        pytest.skip("run npm ci in the synthetic Cedar probe to enable native recapture")

    result = subprocess.run(
        ["node", "capture.mjs"],
        cwd=SCHEMA_CHECKED,
        check=True,
        capture_output=True,
    )

    assert result.stdout == (SCHEMA_CHECKED / "native-output.json").read_bytes()
    assert result.stderr == b""


def test_cedar_profile_rejects_tampering_even_after_rehashing() -> None:
    graph = CedarBundle.from_json(BUNDLE.read_text(encoding="utf-8")).to_ir()
    with pytest.raises(CedarBundleFormatError, match="semantic digest"):
        _validate_cedar_profile(replace(graph, facts=graph.facts[:-1]))

    policy_set = next(entity for entity in graph.entities if entity.kind == "policy_set")
    complete = tuple(
        replace(fact, value=True)
        if (fact.subject, fact.predicate) == (policy_set.id, "policy_inventory_complete")
        else fact
        for fact in graph.facts
    )
    with pytest.raises(CedarBundleFormatError, match="cannot claim complete"):
        _validate_cedar_profile(rehash(replace(graph, facts=complete)))

    decision = next(entity for entity in graph.entities if entity.kind == "decision")
    bad_evidence = tuple(
        replace(fact, evidence=(Evidence(graph.sources[0].id, "", "exact", "accepted"),))
        if fact.subject == decision.id and fact.predicate == "outcome"
        else fact
        for fact in graph.facts
    )
    with pytest.raises(CedarBundleFormatError, match="invalid evidence state"):
        _validate_cedar_profile(rehash(replace(graph, facts=bad_evidence)))


def replace_fact(graph: AuthorityIR, subject: str, predicate: str, **changes: Any) -> AuthorityIR:
    facts = tuple(
        replace(fact, **changes)
        if (fact.subject, fact.predicate) == (subject, predicate)
        else fact
        for fact in graph.facts
    )
    return rehash(replace(graph, facts=facts))


def test_cedar_profile_rejects_structural_source_entity_and_fact_failures() -> None:
    graph = CedarBundle.from_json(BUNDLE.read_text(encoding="utf-8")).to_ir()
    with pytest.raises(CedarBundleFormatError, match="structurally invalid"):
        _validate_cedar_profile(replace(graph, edges=graph.edges[:-1]))
    extra_source = replace(graph.sources[0], id="source:other")
    with pytest.raises(CedarBundleFormatError, match="exactly one source"):
        _validate_cedar_profile(replace(graph, sources=(*graph.sources, extra_source)))
    with pytest.raises(CedarBundleFormatError, match="unsupported source"):
        _validate_cedar_profile(
            replace(graph, sources=(replace(graph.sources[0], adapter="future"),))
        )
    future = Entity(_entity_id("future", "record"), "future", "record")
    with pytest.raises(CedarBundleFormatError, match="unsupported entities"):
        _validate_cedar_profile(rehash(replace(graph, entities=(*graph.entities, future))))

    root = next(entity for entity in graph.entities if entity.kind == "policy_set")
    warning = next(
        fact
        for fact in graph.facts
        if (fact.subject, fact.predicate) == (root.id, "validation_warnings")
    )
    renamed = replace(
        warning,
        id=_fact_id(warning.subject, "future"),
        predicate="future",
    )
    facts = tuple(renamed if fact is warning else fact for fact in graph.facts)
    with pytest.raises(CedarBundleFormatError, match="unsupported predicate"):
        _validate_cedar_profile(rehash(replace(graph, facts=facts)))
    no_evidence = replace_fact(graph, root.id, "validation_warnings", evidence=())
    with pytest.raises(CedarBundleFormatError, match="unsupported evidence"):
        _validate_cedar_profile(no_evidence)
    name_mismatch = replace_fact(graph, root.id, "name", value="other")
    with pytest.raises(CedarBundleFormatError, match="name does not match"):
        _validate_cedar_profile(name_mismatch)
    incomplete = rehash(
        replace(
            graph,
            facts=tuple(
                fact
                for fact in graph.facts
                if (fact.subject, fact.predicate) != (root.id, "validation_warnings")
            ),
        )
    )
    with pytest.raises(CedarBundleFormatError, match="profile is incomplete"):
        _validate_cedar_profile(incomplete)


def test_cedar_profile_rejects_semantically_inconsistent_records() -> None:
    graph = CedarBundle.from_json(BUNDLE.read_text(encoding="utf-8")).to_ir()
    root = next(entity for entity in graph.entities if entity.kind == "policy_set")
    observed = next(
        fact
        for fact in graph.facts
        if (fact.subject, fact.predicate) == (root.id, "observed_policies")
    )
    duplicated = replace_fact(
        graph, root.id, "observed_policies", value=[*observed.value, observed.value[0]]
    )
    with pytest.raises(CedarBundleFormatError, match="observed policies"):
        _validate_cedar_profile(duplicated)
    bad_status = replace_fact(graph, root.id, "validation_status", value="unknown")
    with pytest.raises(CedarBundleFormatError, match="validation status"):
        _validate_cedar_profile(bad_status)

    decision = next(entity for entity in graph.entities if entity.kind == "decision")
    invalid_decision = replace_fact(graph, decision.id, "outcome", value="maybe")
    with pytest.raises(CedarBundleFormatError, match="invalid decision"):
        _validate_cedar_profile(invalid_decision)
    determining = next(
        fact
        for fact in graph.facts
        if (fact.subject, fact.predicate) == (decision.id, "determining_policies")
    )
    duplicate_policy = replace_fact(
        graph,
        decision.id,
        "determining_policies",
        value=[*determining.value, determining.value[0]],
    )
    with pytest.raises(CedarBundleFormatError, match="invalid policy references"):
        _validate_cedar_profile(duplicate_policy)


def test_cedar_profile_rejects_source_and_validation_contradictions() -> None:
    mapped = CedarBundle.from_json(text(with_mapping())).to_ir()
    root = next(entity for entity in mapped.entities if entity.kind == "policy_set")
    mapping_fact = next(
        fact
        for fact in mapped.facts
        if (fact.subject, fact.predicate) == (root.id, "mapping")
    )
    wrong_mapping = copy.deepcopy(mapping_fact.value)
    wrong_mapping["source"] = "entities.json"
    with pytest.raises(CedarBundleFormatError, match="deployment_mapping source"):
        _validate_cedar_profile(replace_fact(mapped, root.id, "mapping", value=wrong_mapping))

    graph = CedarBundle.from_json(BUNDLE.read_text(encoding="utf-8")).to_ir()
    root = next(entity for entity in graph.entities if entity.kind == "policy_set")
    contradiction = replace_fact(graph, root.id, "validation_errors", value=["policy4"])
    with pytest.raises(CedarBundleFormatError, match="status contradicts errors"):
        _validate_cedar_profile(contradiction)

    decision = next(entity for entity in graph.entities if entity.kind == "decision")
    wrong_decision_source = replace_fact(
        graph, decision.id, "source", value="entities.json"
    )
    with pytest.raises(CedarBundleFormatError, match="decision has an invalid source"):
        _validate_cedar_profile(wrong_decision_source)

    request = next(entity for entity in graph.entities if entity.kind == "request")
    wrong_request_source = replace_fact(
        graph, request.id, "source", value="native-output.json"
    )
    with pytest.raises(CedarBundleFormatError, match="request has an invalid source"):
        _validate_cedar_profile(wrong_request_source)


def test_native_capture_is_byte_exact_when_the_pinned_package_is_installed() -> None:
    package = ROOT / "node_modules" / "@cedar-policy" / "cedar-wasm"
    if not package.is_dir():
        pytest.skip("run npm ci in the Cedar fixture directory to enable native recapture")

    result = subprocess.run(
        ["node", "capture.mjs"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )

    assert result.stdout == (ROOT / "native-output.json").read_bytes()
    assert result.stderr == b""


def test_a_reviewed_mapping_round_trips_without_becoming_authority() -> None:
    raw = with_mapping()
    bundle = CedarBundle.from_json(text(raw))

    assert bundle.mapping is not None
    assert bundle.mapping.mapping_version == 1
    assert bundle.mapping.target.agent == "document-agent"
    assert bundle.mapping.principal.cedar_types == ("Workload",)
    assert [item.tool for item in bundle.mapping.actions] == [
        "create_document",
        "view_document",
    ]
    assert [item.cedar_type for item in bundle.mapping.resources] == ["Document", "Drive"]
    assert bundle.mapping.request_domain.evidence.review == "accepted"
    assert CedarBundle.from_json(bundle.to_json()) == bundle
    graph = bundle.to_ir()
    policy_set = next(entity for entity in graph.entities if entity.kind == "policy_set")
    mapping = next(
        fact.value
        for fact in graph.facts
        if (fact.subject, fact.predicate) == (policy_set.id, "mapping")
    )
    assert mapping == bundle.mapping.as_dict()


def test_unreviewed_mapping_evidence_carries_no_accountability_claim() -> None:
    raw = with_mapping()
    raw["mapping"]["request_domain"]["evidence"] = {
        "confidence": "unknown",
        "review": "unreviewed",
        "reviewer": None,
        "expires": None,
    }

    bundle = CedarBundle.from_json(text(raw))

    assert bundle.mapping is not None
    assert bundle.mapping.request_domain.evidence.reviewer is None


def test_failed_native_validation_requires_an_error_identifier() -> None:
    raw = raw_bundle()
    raw["validation"]["status"] = "failure"
    raw["validation"]["errors"] = ["policy4"]

    bundle = CedarBundle.from_json(text(raw))

    assert bundle.validation.errors == ("policy4",)


def test_source_verification_names_the_bad_locator() -> None:
    bundle = CedarBundle.from_json(BUNDLE.read_text(encoding="utf-8"))
    contents = {source.locator: (ROOT / source.locator).read_bytes() for source in bundle.sources}

    missing = dict(contents)
    missing.pop("entities.json")
    with pytest.raises(CedarBundleFormatError, match="declared locators"):
        bundle.verify_sources(missing)

    wrong_type = dict(contents)
    wrong_type["entities.json"] = "not bytes"  # type: ignore[assignment]
    with pytest.raises(CedarBundleFormatError, match="entities.json must be bytes"):
        bundle.verify_sources(wrong_type)

    tampered = dict(contents)
    tampered["entities.json"] += b"\n"
    with pytest.raises(CedarBundleFormatError, match="entities.json does not match"):
        bundle.verify_sources(tampered)

    with pytest.raises(CedarBundleFormatError, match="locator mapping"):
        bundle.verify_sources([])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{", "not valid JSON at line"),
        ("NaN", "not valid JSON"),
        ("[]", "root must be an object"),
        ("{}", "missing field 'bundle_version'"),
        ('{"bundle_version":true}', "version type"),
        ('{"bundle_version":2}', "version 2"),
    ],
)
def test_reader_rejects_malformed_roots(payload: str, message: str) -> None:
    with pytest.raises(CedarBundleFormatError, match=message):
        CedarBundle.from_json(payload)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("cedar",), [], "cedar must be an object"),
        (("cedar", "language_version"), "", "non-empty stripped string"),
        (("cedar", "package_integrity"), "sha256-no", "npm SHA-512 SRI"),
        (("cedar", "package_integrity"), "sha512-YQ==", "npm SHA-512 SRI"),
        (("adapter", "version"), 0, "positive integer"),
        (("sources",), [], "sources must be a non-empty array"),
        (("sources", 0, "kind"), "future", "kind has an invalid value"),
        (("sources", 0, "locator"), "bad\\request.json", "repository-relative POSIX"),
        (("sources", 0, "locator"), "../request.json", "repository-relative POSIX"),
        (("sources", 0, "content_sha256"), "A" * 64, "lowercase SHA-256"),
        (("sources", 0, "origin"), " external ", "origin must be null or non-empty"),
        (("sources", 0, "origin_revision"), "", "origin_revision must be null or non-empty"),
        (("validation", "status"), "unknown", "status has an invalid value"),
        (("validation", "location"), "validation", "must be a JSON Pointer"),
        (("validation", "warnings"), "none", "must be an array of strings"),
        (("decisions",), [], "decisions must be a non-empty array"),
        (("decisions", 0, "decision"), "maybe", "decision has an invalid value"),
        (("decisions", 0, "schema_checked"), 0, "must be a boolean"),
        (("decisions", 0, "location"), "/bad~2pointer", "must be a JSON Pointer"),
        (("decisions", 0, "determining_policies"), [""], "non-empty and stripped"),
        (("decisions", 0, "error_policies"), ["p", "p"], "contains duplicates"),
    ],
)
def test_reader_rejects_invalid_record_values(
    path: tuple[str | int, ...], value: Any, message: str
) -> None:
    raw = raw_bundle()
    set_path(raw, path, value)

    with pytest.raises(CedarBundleFormatError, match=message):
        CedarBundle.from_json(text(raw))


def test_reader_rejects_missing_unknown_and_duplicate_records() -> None:
    missing = raw_bundle()
    missing["adapter"].pop("name")
    with pytest.raises(CedarBundleFormatError, match="missing field 'name'"):
        CedarBundle.from_json(text(missing))

    extra = raw_bundle()
    extra["adapter"]["surprise"] = True
    with pytest.raises(CedarBundleFormatError, match="unknown field 'surprise'"):
        CedarBundle.from_json(text(extra))

    duplicate_source = raw_bundle()
    duplicate_source["sources"].append(copy.deepcopy(duplicate_source["sources"][0]))
    with pytest.raises(CedarBundleFormatError, match="duplicate locators"):
        CedarBundle.from_json(text(duplicate_source))

    missing_kind = raw_bundle()
    missing_kind["sources"] = [
        source for source in missing_kind["sources"] if source["kind"] != "policy_set"
    ]
    with pytest.raises(CedarBundleFormatError, match="missing required kind 'policy_set'"):
        CedarBundle.from_json(text(missing_kind))

    duplicate_decision = raw_bundle()
    duplicate_decision["decisions"].append(copy.deepcopy(duplicate_decision["decisions"][0]))
    with pytest.raises(CedarBundleFormatError, match="duplicate ids"):
        CedarBundle.from_json(text(duplicate_decision))


def test_validation_status_and_errors_cannot_contradict() -> None:
    success_with_error = raw_bundle()
    success_with_error["validation"]["errors"] = ["policy4"]
    with pytest.raises(CedarBundleFormatError, match="successful validation"):
        CedarBundle.from_json(text(success_with_error))

    failure_without_error = raw_bundle()
    failure_without_error["validation"]["status"] = "failure"
    with pytest.raises(CedarBundleFormatError, match="failed validation"):
        CedarBundle.from_json(text(failure_without_error))


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("mapping", "request_domain", "completeness"), "unknown", "completeness"),
        (("mapping", "mapping_version"), 2, "unsupported Cedar mapping version 2"),
        (("mapping", "principal", "cedar_types"), [], "non-empty and stripped"),
        (("mapping", "actions"), [], "actions must be a non-empty array"),
        (("mapping", "resources"), [], "resources must be a non-empty array"),
        (("mapping", "request_domain", "evidence", "confidence"), "maybe", "invalid state"),
        (("mapping", "request_domain", "evidence", "reviewer"), None, "needs a reviewer"),
        (("mapping", "request_domain", "evidence", "reviewer"), " reviewer ", "needs a reviewer"),
        (("mapping", "request_domain", "evidence", "expires"), None, "needs an expiry"),
        (("mapping", "request_domain", "evidence", "expires"), "2027-02-29", "canonical expiry"),
    ],
)
def test_mapping_reader_rejects_untrustworthy_shapes(
    path: tuple[str | int, ...], value: Any, message: str
) -> None:
    raw = with_mapping()
    set_path(raw, path, value)

    with pytest.raises(CedarBundleFormatError, match=message):
        CedarBundle.from_json(text(raw))


def test_unreviewed_evidence_cannot_claim_reviewer_or_expiry() -> None:
    for field, value in (("reviewer", "someone"), ("expires", "2027-08-29")):
        raw = with_mapping()
        evidence = raw["mapping"]["request_domain"]["evidence"]
        evidence.update({"review": "unreviewed", "reviewer": None, "expires": None})
        evidence[field] = value
        with pytest.raises(CedarBundleFormatError, match="cannot carry reviewer or expiry"):
            CedarBundle.from_json(text(raw))


def test_duplicate_mapping_pairs_are_rejected() -> None:
    for field in ("actions", "resources"):
        raw = with_mapping()
        raw["mapping"][field].append(copy.deepcopy(raw["mapping"][field][0]))
        with pytest.raises(CedarBundleFormatError, match="conflicting members"):
            CedarBundle.from_json(text(raw))


def test_mapping_source_members_must_be_unique() -> None:
    raw = with_mapping()
    raw["mapping"]["actions"][1]["cedar"] = raw["mapping"]["actions"][0]["cedar"]

    with pytest.raises(CedarBundleFormatError, match="conflicting members"):
        CedarBundle.from_json(text(raw))


def test_every_reference_must_name_the_right_source_kind() -> None:
    cases = [
        (("validation", "source"), "entities.json", "validation must reference"),
        (("decisions", 0, "request"), "entities.json", "declared request source"),
        (("decisions", 0, "source"), "entities.json", "declared native_output source"),
    ]
    for path, value, message in cases:
        raw = raw_bundle()
        set_path(raw, path, value)
        with pytest.raises(CedarBundleFormatError, match=message):
            CedarBundle.from_json(text(raw))

    mapping = with_mapping()
    mapping["mapping"]["source"] = "entities.json"
    with pytest.raises(CedarBundleFormatError, match="deployment_mapping source"):
        CedarBundle.from_json(text(mapping))
