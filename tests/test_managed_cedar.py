from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from agentmandate._managed_cedar import ManagedOracle, ManagedOracleFormatError

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
