from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from agentmandate._ir import AuthorityIR, Entity, IRFormatError, Source, _analyse_ir, _entity_id
from agentmandate._managed_cedar import (
    ManagedOracle,
    ManagedOracleFormatError,
    _profile_digest,
    _validate_managed_profile,
    analyse_managed_cedar,
    compare_managed_cedar,
)
from agentmandate.manifest import load

ROOT = Path(__file__).parents[1] / "docs" / "evidence" / "agentcore-refund-policy"
ORACLE = ROOT / "managed-oracle-v1.json"


def raw_oracle() -> dict[str, Any]:
    return json.loads(ORACLE.read_text(encoding="utf-8"))


def source_bytes(oracle: ManagedOracle) -> dict[str, bytes]:
    return {source.locator: (ROOT / source.locator).read_bytes() for source in oracle.sources}


def set_path(raw: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    target: Any = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


def text(raw: Any) -> str:
    return json.dumps(raw, allow_nan=True)


def replace_source(
    raw: dict[str, Any], contents: dict[str, bytes], locator: str, value: Any
) -> None:
    content = value if isinstance(value, bytes) else json.dumps(value).encode()
    contents[locator] = content
    source = next(item for item in raw["sources"] if item["locator"] == locator)
    source["content_sha256"] = hashlib.sha256(content).hexdigest()


def oracle_and_contents(
    mutate: Any | None = None,
) -> tuple[ManagedOracle, dict[str, bytes]]:
    raw = raw_oracle()
    oracle = ManagedOracle.from_json(text(raw))
    contents = source_bytes(oracle)
    if mutate is not None:
        mutate(raw, contents)
    return ManagedOracle.from_json(text(raw)), contents


def test_live_managed_oracle_is_canonical_and_digest_bound() -> None:
    committed = ORACLE.read_text(encoding="utf-8")
    oracle = ManagedOracle.from_json(committed)

    assert oracle.to_json() == committed
    assert oracle.provider.name == "aws-agentcore"
    assert oracle.state.policy_engine_mode == "ENFORCE"
    assert oracle.tool_inventory.complete is True
    assert [item.name for item in oracle.policy_inventory.members] == ["RefundIamUnderLimit"]
    assert [(item.id, item.outcome, item.reason) for item in oracle.decisions] == [
        ("allow-under-limit", "allow", "managed_allow"),
        ("deny-over-limit", "deny", "default_deny"),
    ]
    assert oracle.decisions[0].request_key == (
        '{"arguments":{"amount":500},"method":"tools/call",'
        '"tool":"RefundIamTarget___process_refund"}'
    )
    oracle.verify_sources(source_bytes(oracle))


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("managed_oracle_version",), True, "version type"),
        (("managed_oracle_version",), 2, "version 2"),
        (("capture_date",), "20260229", "canonical date"),
        (("capture_date",), "2027-02-29", "canonical date"),
        (("adapter", "name"), "other", "unsupported adapter"),
        (("adapter", "version"), 0, "positive integer"),
        (("mapping", "mapping_version"), 2, "mapping is invalid"),
        (("provider", "region"), " us-east-1", "non-empty stripped"),
        (("state", "source"), "state\\file.json", "repository-relative"),
        (("state", "source"), "../state.json", "repository-relative"),
        (("sources",), [], "sources must be a non-empty"),
        (("sources", 0, "content_sha256"), "bad", "lowercase SHA-256"),
        (("sources", 0, "kind"), "schema", "kind is invalid"),
        (("tool_inventory", "complete"), "yes", "must be boolean"),
        (("tool_inventory", "members"), [], "non-empty"),
        (("sanitization", "omitted"), "none", "array of strings"),
        (("sanitization", "omitted"), ["same", "same"], "duplicates"),
        (("policy_inventory", "members"), {}, "must be an array"),
        (("policy_inventory", "members"), [], "non-empty and unique"),
        (("decisions",), [], "decisions must be a non-empty"),
        (("decisions", 0, "outcome"), "maybe", "invalid outcome"),
        (("decisions", 0, "reason"), "default_deny", "contradicts reason"),
        (("decisions", 0, "arguments"), [], "must be a JSON object"),
        (("decisions", 0, "arguments"), {"bad": float("nan")}, "not valid JSON"),
        (("sanitization", "decision_messages_changed"), "no", "must be boolean"),
        (("sanitization", "aliases"), [], "must be non-empty"),
    ],
)
def test_reader_rejects_malformed_records(
    path: tuple[str | int, ...], value: Any, message: str
) -> None:
    raw = raw_oracle()
    set_path(raw, path, value)

    with pytest.raises(ManagedOracleFormatError, match=message):
        ManagedOracle.from_json(text(raw))


def test_reader_rejects_shape_reference_and_duplicate_failures() -> None:
    with pytest.raises(ManagedOracleFormatError, match="not valid JSON"):
        ManagedOracle.from_json("[")
    with pytest.raises(ManagedOracleFormatError, match="root must be an object"):
        ManagedOracle.from_json("[]")
    with pytest.raises(ManagedOracleFormatError, match="missing field"):
        ManagedOracle.from_json("{}")

    raw = raw_oracle()
    raw["schema_checked"] = True
    with pytest.raises(ManagedOracleFormatError, match="unknown field 'schema_checked'"):
        ManagedOracle.from_json(text(raw))

    raw = raw_oracle()
    raw["decisions"][0]["determining_policies"] = []
    with pytest.raises(ManagedOracleFormatError, match="determining_policies"):
        ManagedOracle.from_json(text(raw))

    for mutate, message in [
        (lambda value: value["sources"].append(copy.deepcopy(value["sources"][0])), "duplicate"),
        (
            lambda value: value.update(
                sources=[item for item in value["sources"] if item["kind"] != "policy"]
            ),
            "missing required kind",
        ),
        (
            lambda value: value["decisions"].append(copy.deepcopy(value["decisions"][0])),
            "duplicates",
        ),
        (
            lambda value: value["sanitization"]["aliases"].append(
                copy.deepcopy(value["sanitization"]["aliases"][0])
            ),
            "aliases conflict",
        ),
    ]:
        raw = raw_oracle()
        mutate(raw)
        with pytest.raises(ManagedOracleFormatError, match=message):
            ManagedOracle.from_json(text(raw))

    raw = raw_oracle()
    raw["state"]["source"] = "allow-request.json"
    with pytest.raises(ManagedOracleFormatError, match="must name source kind"):
        ManagedOracle.from_json(text(raw))
    raw = raw_oracle()
    raw["decisions"][0]["request"] = "managed-state.json"
    with pytest.raises(ManagedOracleFormatError, match="invalid source references"):
        ManagedOracle.from_json(text(raw))

    raw = raw_oracle()
    raw["mapping"]["resources"].append({"cedar_type": "Other", "binding": "other"})
    with pytest.raises(ManagedOracleFormatError, match="exactly one resource"):
        ManagedOracle.from_json(text(raw))


def test_verify_sources_rejects_mapping_and_digest_boundaries() -> None:
    oracle = ManagedOracle.from_json(ORACLE.read_text(encoding="utf-8"))
    contents = source_bytes(oracle)

    with pytest.raises(ManagedOracleFormatError, match="locator 'allow-request.json'"):
        oracle.verify_sources(
            {key: value for key, value in contents.items() if key != "allow-request.json"}
        )
    with pytest.raises(ManagedOracleFormatError, match="locator 'extra.json'"):
        oracle.verify_sources(contents | {"extra.json": b"extra"})
    with pytest.raises(ManagedOracleFormatError, match="digest.*allow-request.json"):
        oracle.verify_sources(contents | {"allow-request.json": b"tampered"})
    with pytest.raises(ManagedOracleFormatError, match="locator-to-bytes"):
        oracle.verify_sources({"allow-request.json": "not bytes"})  # type: ignore[dict-item]


@pytest.mark.parametrize(
    ("locator", "mutation", "message"),
    [
        ("mapping.json", lambda value: value | {"mapping_version": 2}, "mapping source.*invalid"),
        (
            "mapping.json",
            lambda value: value | {"target": value["target"] | {"agent": "other"}},
            "mapping source disagrees",
        ),
        ("mandate.yaml", lambda _value: b"not: [valid", "manifest source.*invalid"),
        (
            "tools-list-response.json",
            lambda value: value["result"] | {"tools": []},
            "tool inventory source.*invalid shape",
        ),
        (
            "tool-schema.json",
            lambda _value: [{"name": "other"}],
            "tool schema disagrees",
        ),
        (
            "managed-state.json",
            lambda value: value | {"tool_inventory_complete": False},
            "managed-state source disagrees",
        ),
        ("allow-request.json", lambda value: value | {"method": "other"}, "request source"),
        ("allow-response.json", lambda _value: {"error": {"code": -32002}}, "response source"),
    ],
)
def test_projection_verification_rejects_semantic_disagreement(
    locator: str, mutation: Any, message: str
) -> None:
    raw = raw_oracle()
    oracle = ManagedOracle.from_json(text(raw))
    contents = source_bytes(oracle)
    original: Any
    try:
        original = json.loads(contents[locator])
    except (json.JSONDecodeError, UnicodeDecodeError):
        original = contents[locator]
    replace_source(raw, contents, locator, mutation(original))
    mutated = ManagedOracle.from_json(text(raw))

    with pytest.raises(ManagedOracleFormatError, match=message):
        mutated.verify_sources(contents)


def test_projection_verification_rejects_deeper_join_failures() -> None:
    cases: list[tuple[dict[str, Any], dict[str, bytes], str]] = []

    raw = raw_oracle()
    oracle = ManagedOracle.from_json(text(raw))
    contents = source_bytes(oracle)
    replace_source(raw, contents, "mapping.json", b"{")
    cases.append((raw, contents, "source 'mapping.json' is not valid JSON"))

    raw = raw_oracle()
    raw["mapping"]["target"]["agent"] = "other"
    oracle = ManagedOracle.from_json(text(raw))
    contents = source_bytes(oracle)
    replace_source(raw, contents, "mapping.json", raw["mapping"])
    cases.append((raw, contents, "mapping target disagrees"))

    raw = raw_oracle()
    raw["tool_inventory"]["members"] = ["Other___tool"]
    oracle = ManagedOracle.from_json(text(raw))
    cases.append((raw, source_bytes(oracle), "tool inventory disagrees"))

    raw = raw_oracle()
    oracle = ManagedOracle.from_json(text(raw))
    contents = source_bytes(oracle)
    replace_source(raw, contents, "tool-schema.json", [{}])
    cases.append((raw, contents, "tool schema source.*invalid shape"))

    raw = raw_oracle()
    raw["mapping"]["actions"][0]["cedar"] = 'AgentCore::Action::"Other___tool"'
    oracle = ManagedOracle.from_json(text(raw))
    contents = source_bytes(oracle)
    replace_source(raw, contents, "mapping.json", raw["mapping"])
    cases.append((raw, contents, "actions disagree"))

    raw = raw_oracle()
    oracle = ManagedOracle.from_json(text(raw))
    contents = source_bytes(oracle)
    replace_source(raw, contents, "policy.cedar", b"permit(principal, action, resource);")
    cases.append((raw, contents, "aliases do not join"))

    for candidate, source_content, message in cases:
        with pytest.raises(ManagedOracleFormatError, match=message):
            ManagedOracle.from_json(text(candidate)).verify_sources(source_content)


def test_projection_verification_requires_the_recorded_managed_response_semantics() -> None:
    raw = raw_oracle()
    oracle = ManagedOracle.from_json(text(raw))
    contents = source_bytes(oracle)
    allow = json.loads(contents["allow-response.json"])
    allow["result"]["isError"] = True
    replace_source(raw, contents, "allow-response.json", allow)
    with pytest.raises(ManagedOracleFormatError, match="response source.*disagrees"):
        ManagedOracle.from_json(text(raw)).verify_sources(contents)

    raw = raw_oracle()
    oracle = ManagedOracle.from_json(text(raw))
    contents = source_bytes(oracle)
    raw["decisions"][1]["reason"] = "explicit_deny"
    with pytest.raises(ManagedOracleFormatError, match="response source.*disagrees"):
        ManagedOracle.from_json(text(raw)).verify_sources(contents)


def rehash(graph: AuthorityIR) -> AuthorityIR:
    source = replace(
        graph.sources[0],
        semantic_sha256=_profile_digest(graph.entities, graph.facts, graph.edges),
    )
    return replace(graph, sources=(source,))


def test_managed_oracle_projects_a_closed_standalone_ir_profile() -> None:
    oracle = ManagedOracle.from_json(ORACLE.read_text(encoding="utf-8"))
    graph = oracle.to_ir()

    assert len(graph.entities) == 8
    assert len(graph.edges) == 5
    assert {edge.relation for edge in graph.edges} == {
        "decides_request",
        "enforces_for",
        "maps_to_tool",
    }
    assert {entity.kind for entity in graph.entities} == {
        "decision",
        "enforcement_point",
        "policy",
        "policy_action",
        "request",
        "tool",
    }
    assert not {
        "schema_checked",
        "determining_policies",
    } & {fact.predicate for fact in graph.facts}
    restored = AuthorityIR.from_json(graph.to_json())
    assert restored.to_json() == graph.to_json()
    _validate_managed_profile(restored)
    with pytest.raises(IRFormatError, match="analyzable manifest-v1 profile"):
        _analyse_ir(restored)


def test_managed_ir_profile_rejects_tampering_even_after_rehashing() -> None:
    graph = ManagedOracle.from_json(ORACLE.read_text(encoding="utf-8")).to_ir()
    with pytest.raises(ManagedOracleFormatError, match="semantic digest"):
        _validate_managed_profile(replace(graph, facts=graph.facts[:-1]))

    root = next(entity for entity in graph.entities if entity.kind == "enforcement_point")
    facts = tuple(
        replace(fact, value=fact.value | {"schema_checked": True})
        if fact.subject == root.id and fact.predicate == "oracle"
        else fact
        for fact in graph.facts
    )
    with pytest.raises(ManagedOracleFormatError, match="oracle fact is invalid"):
        _validate_managed_profile(rehash(replace(graph, facts=facts)))

    edge = graph.edges[0]
    edges = (replace(edge, support=()), *graph.edges[1:])
    with pytest.raises(ManagedOracleFormatError, match="structurally invalid"):
        _validate_managed_profile(rehash(replace(graph, edges=edges)))

    extra_source = Source(
        "source:extra",
        "managed-cedar-oracle",
        "memory:extra",
        1,
        "2025-03-26",
        "0" * 64,
        "agentmandate.managed-cedar-oracle",
        1,
        "0" * 64,
    )
    with pytest.raises(ManagedOracleFormatError, match="exactly one source"):
        _validate_managed_profile(replace(graph, sources=(*graph.sources, extra_source)))

    with pytest.raises(ManagedOracleFormatError, match="unsupported source"):
        _validate_managed_profile(
            replace(graph, sources=(replace(graph.sources[0], kind="other"),))
        )

    extra_root = Entity(_entity_id("enforcement_point", "other"), "enforcement_point", "other")
    with pytest.raises(ManagedOracleFormatError, match="one enforcement point"):
        _validate_managed_profile(
            rehash(
                replace(
                    graph, entities=tuple(sorted((*graph.entities, extra_root), key=lambda x: x.id))
                )
            )
        )

    no_oracle = tuple(
        fact for fact in graph.facts if not (fact.subject == root.id and fact.predicate == "oracle")
    )
    with pytest.raises(ManagedOracleFormatError, match="no unique oracle fact"):
        _validate_managed_profile(rehash(replace(graph, facts=no_oracle)))

    extra_policy = Entity(_entity_id("policy", "extra"), "policy", "extra")
    with pytest.raises(ManagedOracleFormatError, match="does not match its oracle"):
        _validate_managed_profile(
            rehash(
                replace(
                    graph,
                    entities=tuple(
                        sorted((*graph.entities, extra_policy), key=lambda item: item.id)
                    ),
                )
            )
        )

    with pytest.raises(ManagedOracleFormatError, match="content digest"):
        _validate_managed_profile(
            replace(graph, sources=(replace(graph.sources[0], content_sha256="0" * 64),))
        )


def test_private_alignment_preserves_authority_and_exact_request_scope() -> None:
    oracle, contents = oracle_and_contents()
    mandate = load(ROOT / "mandate.yaml")
    result = analyse_managed_cedar(mandate, oracle, contents, as_of=date(2027, 8, 29))

    assert result.authority.reachable_tools == {"process_refund"}
    assert result.findings == ()
    assert [(item.decision, item.alignment) for item in result.alignments] == [
        ("allow-under-limit", "aligned_allow"),
        ("deny-over-limit", "enforcement_narrows_request"),
    ]
    assert all(len(item.support) == 3 for item in result.alignments)
    assert result.clean is False
    rendered = result.as_dict()
    assert rendered["clean"] is False
    assert rendered["alignments"][1]["outcome"] == "deny"


def test_private_alignment_fails_closed_for_source_and_review_failures() -> None:
    mandate = load(ROOT / "mandate.yaml")
    oracle, contents = oracle_and_contents()
    tampered = contents | {"allow-response.json": b"tampered"}
    result = analyse_managed_cedar(mandate, oracle, tampered, as_of=date(2026, 8, 29))
    assert [item.code for item in result.findings] == ["managed.source-untrusted"]
    assert {item.alignment for item in result.alignments} == {"unresolved"}

    expired = analyse_managed_cedar(mandate, oracle, contents, as_of=date(2027, 8, 30))
    assert [item.code for item in expired.findings] == ["managed.mapping-untrusted"]
    assert {item.alignment for item in expired.alignments} == {"unresolved"}
    assert expired.as_dict()["findings"] == [
        {
            "code": "managed.mapping-untrusted",
            "message": "managed Cedar mapping is not exact, accepted, and current",
        }
    ]

    with pytest.raises(ManagedOracleFormatError, match="as_of must be a date"):
        analyse_managed_cedar(
            mandate,
            oracle,
            contents,
            as_of=datetime(2026, 8, 29),  # type: ignore[arg-type]
        )


def test_private_alignment_refuses_a_foreign_or_unreachable_mandate() -> None:
    oracle, contents = oracle_and_contents()
    mandate = load(ROOT / "mandate.yaml")
    foreign = replace(mandate, agent="other")
    result = analyse_managed_cedar(foreign, oracle, contents, as_of=date(2026, 8, 29))
    assert "managed.target-mismatch" in {item.code for item in result.findings}

    unreachable = replace(
        mandate,
        tools=(replace(mandate.tools[0], name="other"),),
    )
    result = analyse_managed_cedar(unreachable, oracle, contents, as_of=date(2026, 8, 29))
    assert "managed.request-unmapped" in {item.code for item in result.findings}
    assert {item.alignment for item in result.alignments} == {"unresolved"}


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda raw, contents: (
                raw["state"].update(policy_engine_mode="LOG_ONLY"),
                _mutate_state(raw, contents, ("gateway", "policy_engine_mode"), "LOG_ONLY"),
            ),
            "managed.enforcement-ineligible",
        ),
        (
            lambda raw, contents: (
                raw["state"].update(requested_validation_mode="IGNORE_ALL_FINDINGS"),
                _mutate_state(
                    raw,
                    contents,
                    ("policy", "requested_validation_mode"),
                    "IGNORE_ALL_FINDINGS",
                ),
            ),
            "managed.enforcement-ineligible",
        ),
        (
            lambda raw, contents: (
                raw["tool_inventory"].update(complete=False),
                _mutate_state(raw, contents, ("tool_inventory_complete",), False),
            ),
            "managed.inventory-incomplete",
        ),
        (
            lambda raw, contents: _mutate_mapping_review(raw, contents, "contested"),
            "managed.mapping-untrusted",
        ),
        (
            lambda raw, contents: (
                raw["sanitization"].update(decision_messages_changed=True),
                _mutate_state(
                    raw,
                    contents,
                    ("sanitization", "decision_messages_changed"),
                    True,
                ),
            ),
            "managed.sanitization-changed-decision",
        ),
        (
            lambda raw, contents: _mutate_principal(raw, contents, "service"),
            "managed.principal-mismatch",
        ),
        (
            lambda raw, contents: _mutate_resource_type(raw, contents, "Other::Gateway"),
            "managed.resource-mismatch",
        ),
    ],
)
def test_private_alignment_names_each_trust_failure(mutate: Any, code: str) -> None:
    oracle, contents = oracle_and_contents(mutate)
    result = analyse_managed_cedar(
        load(ROOT / "mandate.yaml"),
        oracle,
        contents,
        as_of=date(2026, 8, 29),
    )

    assert code in {item.code for item in result.findings}
    assert {item.alignment for item in result.alignments} == {"unresolved"}


def _mutate_state(
    raw: dict[str, Any],
    contents: dict[str, bytes],
    path: tuple[str, ...],
    value: Any,
) -> None:
    state = json.loads(contents["managed-state.json"])
    set_path(state, path, value)
    replace_source(raw, contents, "managed-state.json", state)


def _mutate_mapping_review(raw: dict[str, Any], contents: dict[str, bytes], review: str) -> None:
    raw["mapping"]["request_domain"]["evidence"]["review"] = review
    replace_source(raw, contents, "mapping.json", raw["mapping"])


def _mutate_principal(raw: dict[str, Any], contents: dict[str, bytes], principal: str) -> None:
    raw["mapping"]["principal"]["mandate_principal"] = principal
    replace_source(raw, contents, "mapping.json", raw["mapping"])


def _mutate_resource_type(raw: dict[str, Any], contents: dict[str, bytes], cedar_type: str) -> None:
    raw["mapping"]["resources"][0]["cedar_type"] = cedar_type
    raw["sanitization"]["aliases"][0]["cedar_type"] = cedar_type
    replace_source(raw, contents, "mapping.json", raw["mapping"])


def test_private_alignment_rejects_an_evaluation_before_capture() -> None:
    oracle, contents = oracle_and_contents()
    result = analyse_managed_cedar(
        load(ROOT / "mandate.yaml"),
        oracle,
        contents,
        as_of=date(2026, 8, 28),
    )

    assert [item.code for item in result.findings] == ["managed.capture-in-future"]
    assert {item.alignment for item in result.alignments} == {"unresolved"}


def candidate_allowing_2000() -> tuple[ManagedOracle, dict[str, bytes]]:
    def mutate(raw: dict[str, Any], contents: dict[str, bytes]) -> None:
        decision = next(item for item in raw["decisions"] if item["id"] == "deny-over-limit")
        decision["outcome"] = "allow"
        decision["reason"] = "managed_allow"
        response = {
            "jsonrpc": "2.0",
            "id": "deny-over-limit",
            "result": {
                "content": [{"text": '{"processed":true,"amount":2000}', "type": "text"}],
                "isError": False,
            },
        }
        replace_source(raw, contents, "deny-response.json", response)
        policy = (
            (ROOT / "policy.cedar")
            .read_text(encoding="utf-8")
            .replace("amount < 1000", "amount < 3000")
        )
        replace_source(raw, contents, "policy.cedar", policy.encode())

    return oracle_and_contents(mutate)


def test_private_revision_comparison_classifies_all_four_outcome_pairs() -> None:
    baseline, baseline_contents = oracle_and_contents()
    candidate, candidate_contents = candidate_allowing_2000()
    mandate = load(ROOT / "mandate.yaml")
    widened = compare_managed_cedar(
        mandate,
        baseline,
        baseline_contents,
        candidate,
        candidate_contents,
        as_of=date(2026, 8, 29),
    )

    assert [item.classification for item in widened.changes] == [
        "stable_allow",
        "widens",
    ]
    assert widened.findings == ()
    assert widened.clean is False
    assert widened.as_dict()["changes"][1]["classification"] == "widens"

    tightened = compare_managed_cedar(
        mandate,
        candidate,
        candidate_contents,
        baseline,
        baseline_contents,
        as_of=date(2026, 8, 29),
    )
    assert [item.classification for item in tightened.changes] == [
        "stable_allow",
        "tightens",
    ]
    stable = compare_managed_cedar(
        mandate,
        baseline,
        baseline_contents,
        baseline,
        baseline_contents,
        as_of=date(2026, 8, 29),
    )
    assert [item.classification for item in stable.changes] == [
        "stable_allow",
        "stable_deny",
    ]


def test_private_revision_comparison_refuses_changed_boundaries_and_requests() -> None:
    mandate = load(ROOT / "mandate.yaml")
    baseline, baseline_contents = oracle_and_contents()

    def region(raw: dict[str, Any], _contents: dict[str, bytes]) -> None:
        raw["provider"]["region"] = "us-west-2"

    candidate, candidate_contents = oracle_and_contents(region)
    changed = compare_managed_cedar(
        mandate,
        baseline,
        baseline_contents,
        candidate,
        candidate_contents,
        as_of=date(2026, 8, 29),
    )
    assert [item.code for item in changed.findings] == ["managed.comparison-boundary-changed"]
    assert changed.changes == ()

    def request(raw: dict[str, Any], contents: dict[str, bytes]) -> None:
        decision = raw["decisions"][0]
        decision["arguments"] = {"amount": 600}
        body = json.loads(contents[decision["request"]])
        body["params"]["arguments"] = {"amount": 600}
        replace_source(raw, contents, decision["request"], body)

    candidate, candidate_contents = oracle_and_contents(request)
    changed = compare_managed_cedar(
        mandate,
        baseline,
        baseline_contents,
        candidate,
        candidate_contents,
        as_of=date(2026, 8, 29),
    )
    assert [item.code for item in changed.findings] == ["managed.comparison-requests-changed"]

    expired = compare_managed_cedar(
        mandate,
        baseline,
        baseline_contents,
        baseline,
        baseline_contents,
        as_of=date(2027, 8, 30),
    )
    assert [item.code for item in expired.findings] == ["managed.comparison-untrusted"]
