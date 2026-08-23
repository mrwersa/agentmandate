from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from agentmandate import loads
from agentmandate._ir import (
    RESULT_VERSION,
    IRFormatError,
    _analyse_ir,
    _canonical_result_bytes,
    _from_mandate,
    _IRAnalysis,
)
from agentmandate.manifest import Money

FIXTURES = Path(__file__).parent / "fixtures"

CLEAN = """
agent: clean
tools:
  - name: look
    effect: read
"""

TRUNCATED = """
agent: truncated
tools:
  - name: mint
    effect: read
    produces: token
    unbounded: true
"""

BREACHED = """
agent: breached
limits:
  total: {amount: 500, currency: GBP}
tools:
  - name: open_case
    effect: read
    produces: case
    unbounded: true
  - name: issue_refund
    effect: irreversible
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: {amount: 500, currency: GBP}
"""


def result(manifest: str, depth: int) -> _IRAnalysis:
    return _analyse_ir(_from_mandate(loads(manifest)), depth=depth)


@pytest.mark.parametrize(
    ("name", "manifest", "depth", "truncated", "breached"),
    [
        ("clean", CLEAN, 2, False, False),
        ("truncated", TRUNCATED, 1, True, False),
        ("breached", BREACHED, 4, True, True),
    ],
)
def test_canonical_result_fixtures_round_trip(
    name: str,
    manifest: str,
    depth: int,
    truncated: bool,
    breached: bool,
) -> None:
    expected = result(manifest, depth)
    text = (FIXTURES / f"authority-ir-result-v1-{name}.json").read_text(
        encoding="utf-8"
    )

    assert expected.result_version == RESULT_VERSION
    assert expected.authority.truncated is truncated
    assert bool(expected.authority.breaches) is breached
    assert expected.to_json() == text
    restored = _IRAnalysis.from_json(text)
    assert restored == expected
    assert restored.to_json() == text
    if name == "breached":
        cumulative = next(
            breach
            for breach in restored.authority.breaches
            if breach.kind == "cumulative_value"
        )
        assert [step.tool for step in cumulative.path] == [
            "open_case",
            "open_case",
            "issue_refund",
            "issue_refund",
        ]


def test_result_bytes_are_stable_under_reordered_source_tables_and_support() -> None:
    source = _from_mandate(loads(BREACHED))
    reordered = replace(
        source,
        sources=tuple(reversed(source.sources)),
        entities=tuple(reversed(source.entities)),
        facts=tuple(
            replace(fact, evidence=tuple(reversed(fact.evidence)))
            for fact in reversed(source.facts)
        ),
        edges=tuple(
            replace(edge, support=tuple(reversed(edge.support)))
            for edge in reversed(source.edges)
        ),
    )

    assert result(BREACHED, 4).to_json() == _analyse_ir(reordered, depth=4).to_json()


def rehash(raw: dict[str, object]) -> str:
    body = {key: value for key, value in raw.items() if key != "result_sha256"}
    raw["result_sha256"] = hashlib.sha256(_canonical_result_bytes(body)).hexdigest()
    return _canonical_result_bytes(raw).decode("utf-8")


def test_result_reader_rejects_version_digest_and_parameter_tampering() -> None:
    raw = result(CLEAN, 2).as_dict()
    raw["result_version"] = 2
    with pytest.raises(IRFormatError, match="unsupported authority IR result version 2"):
        _IRAnalysis.from_json(json.dumps(raw))

    with pytest.raises(IRFormatError, match="unsupported authority IR result version 2"):
        _IRAnalysis.from_json('{"result_version":2,"future_shape":true}')

    raw = result(CLEAN, 2).as_dict()
    raw["result_sha256"] = "0" * 64
    with pytest.raises(IRFormatError, match="result_sha256 does not match"):
        _IRAnalysis.from_json(json.dumps(raw))

    raw = result(TRUNCATED, 1).as_dict()
    analysis = raw["analysis"]
    assert isinstance(analysis, dict)
    analysis["truncated"] = False
    with pytest.raises(IRFormatError, match="truncation does not match"):
        _IRAnalysis.from_json(rehash(raw))


def test_result_reader_rejects_rehashed_source_authority_and_graph_tampering() -> None:
    raw = result(CLEAN, 2).as_dict()
    source = raw["source_graph"]
    assert isinstance(source, dict)
    source["sha256"] = "0" * 64
    with pytest.raises(IRFormatError, match="source graph digest does not match"):
        _IRAnalysis.from_json(rehash(raw))

    raw = result(CLEAN, 2).as_dict()
    authority = raw["authority"]
    assert isinstance(authority, dict)
    authority["reachable_tools"] = []
    with pytest.raises(IRFormatError, match="authority output does not match"):
        _IRAnalysis.from_json(rehash(raw))

    raw = result(CLEAN, 2).as_dict()
    graph = raw["graph"]
    assert isinstance(graph, dict)
    edges = graph["edges"]
    assert isinstance(edges, list)
    graph["edges"] = [edge for edge in edges if edge["relation"] != "can_reach"]
    with pytest.raises(IRFormatError, match="result graph does not match analysis"):
        _IRAnalysis.from_json(rehash(raw))


def test_result_rejects_noncanonical_values_before_and_during_read() -> None:
    value = result(CLEAN, 2)
    nonfinite = replace(
        value,
        authority=replace(
            value.authority,
            max_extractable=Money(Decimal("NaN"), "GBP"),
        ),
    )
    with pytest.raises(IRFormatError, match="authority output does not match"):
        nonfinite.to_json()

    text = value.to_json().replace('"result_version":1', '"result_version":NaN')
    with pytest.raises(IRFormatError, match="non-canonical value"):
        _IRAnalysis.from_json(text)
    with pytest.raises(IRFormatError, match="non-canonical value"):
        _canonical_result_bytes({"value": float("nan")})


def test_result_object_revalidates_source_identity_and_computed_output() -> None:
    value = result(CLEAN, 2)
    with pytest.raises(IRFormatError, match="result version"):
        replace(value, result_version=2).to_json()
    with pytest.raises(IRFormatError, match="source graph version"):
        replace(value, source_ir_version=2).to_json()
    with pytest.raises(IRFormatError, match="source graph digest"):
        replace(value, source_graph_sha256="0" * 64).to_json()

    missing_reach = replace(
        value.graph,
        edges=tuple(edge for edge in value.graph.edges if edge.relation != "can_reach"),
    )
    with pytest.raises(IRFormatError, match="result graph does not match analysis"):
        replace(value, graph=missing_reach).to_json()


def test_result_reader_has_a_typed_strict_shape_boundary() -> None:
    valid = result(CLEAN, 2).as_dict()
    cases = [
        ("{", "not valid JSON"),
        ("[]", "result must be an object"),
        ("{}", "missing field 'result_version'"),
        (json.dumps({**valid, "extra": True}), "unknown field"),
        (
            json.dumps({key: value for key, value in valid.items() if key != "graph"}),
            "missing field",
        ),
        (json.dumps({**valid, "result_version": True}), "version type"),
        (json.dumps({**valid, "result_sha256": 7}), "must be a string"),
        (json.dumps({**valid, "result_sha256": "bad"}), "lowercase SHA-256"),
        (json.dumps({**valid, "source_graph": []}), "source_graph must be an object"),
        (
            json.dumps(
                {
                    **valid,
                    "source_graph": {"ir_version": 1, "sha256": "bad"},
                }
            ),
            "source_graph.sha256 must be lowercase SHA-256",
        ),
        (json.dumps({**valid, "analysis": []}), "analysis must be an object"),
        (
            json.dumps({**valid, "analysis": {"depth": 0, "truncated": False}}),
            "depth must be positive",
        ),
        (
            json.dumps({**valid, "analysis": {"depth": 2, "truncated": 0}}),
            "truncated must be a boolean",
        ),
        (json.dumps({**valid, "authority": []}), "authority must be an object"),
        (json.dumps({**valid, "graph": []}), "graph must be an object"),
    ]
    for text, message in cases:
        with pytest.raises(IRFormatError, match=message):
            _IRAnalysis.from_json(text)

    changed = result(CLEAN, 2).as_dict()
    source = changed["source_graph"]
    assert isinstance(source, dict)
    source["ir_version"] = 2
    with pytest.raises(IRFormatError, match="source graph version does not match"):
        _IRAnalysis.from_json(rehash(changed))
