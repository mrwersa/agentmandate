from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from agentmandate import loads
from agentmandate._ir import AuthorityIR, IRFormatError, _from_mandate

INVALID = Path(__file__).parent / "fixtures" / "authority-ir-invalid"


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("malformed.json", "not valid JSON at line 2 column"),
        ("snapshot-table-type.json", "sources must be an array"),
        ("source-missing-field.json", "sources[0] is missing field 'locator'"),
        ("entity-extra-field.json", "entities[0] has unknown field 'payload'"),
        (
            "fact-invalid-evidence.json",
            "facts[0].evidence[0].confidence has an invalid value",
        ),
        (
            "evidence-extra-field.json",
            "facts[0].evidence[0] has unknown field 'payload'",
        ),
        ("edge-support-type.json", "edges[0].support must be an array of strings"),
        ("edge-invalid-relation.json", "edges[0].relation has an invalid value"),
        ("duplicate-entity-id.json", "duplicate entity id at entities[1].id"),
    ],
)
def test_committed_malformed_records_have_one_safe_error_boundary(
    name: str, message: str
) -> None:
    content = (INVALID / name).read_text(encoding="utf-8")

    with pytest.raises(IRFormatError, match=re.escape(message)) as caught:
        AuthorityIR.from_json(content)

    assert "secret-value" not in str(caught.value)
    assert "do-not-echo" not in str(caught.value)


def test_root_shape_and_version_failures_are_precise() -> None:
    with pytest.raises(IRFormatError, match="root must be an object"):
        AuthorityIR.from_json("[]")
    with pytest.raises(IRFormatError, match="root is missing field 'ir_version'"):
        AuthorityIR.from_json("{}")
    with pytest.raises(IRFormatError, match="unsupported authority IR version type") as caught:
        AuthorityIR.from_json('{"ir_version":"secret-version"}')
    assert "secret-version" not in str(caught.value)
    with pytest.raises(IRFormatError, match="unsupported authority IR version 2"):
        AuthorityIR.from_json('{"ir_version":2}')


def test_reader_rejects_record_and_scalar_types_without_leaking_values() -> None:
    valid = _from_mandate(
        loads("agent: a\ntools: [{name: t, effect: read}]\n")
    ).as_dict()

    cases = [
        ("sources", 0, None, "sources[0] must be an object"),
        ("entities", 0, None, "entities[0] must be an object"),
        ("facts", 0, None, "facts[0] must be an object"),
        ("edges", 0, None, "edges[0] must be an object"),
        ("sources", 0, ("id", 7), "sources[0].id must be a string"),
        (
            "sources",
            0,
            ("format_version", True),
            "sources[0].format_version must be an integer",
        ),
        (
            "sources",
            0,
            ("producer_version", 7),
            "sources[0].producer_version must be a string or null",
        ),
        ("entities", 0, ("name", 7), "entities[0].name must be a string"),
        ("facts", 0, ("evidence", {}), "facts[0].evidence must be an array"),
        (
            "edges",
            0,
            ("support", ["fact:ok", 7]),
            "edges[0].support must be an array of strings",
        ),
    ]
    for table, index, change, message in cases:
        payload = deepcopy(valid)
        if change is None:
            payload[table][index] = "secret-value"
        else:
            field, value = change
            payload[table][index][field] = value
        with pytest.raises(IRFormatError, match=re.escape(message)) as caught:
            AuthorityIR.from_json(json.dumps(payload))
        assert "secret-value" not in str(caught.value)


def test_reader_rejects_unknown_root_fields_and_non_string_input() -> None:
    payload = _from_mandate(
        loads("agent: a\ntools: [{name: t, effect: read}]\n")
    ).as_dict()
    payload["payload"] = "secret-value"

    with pytest.raises(IRFormatError, match="root has unknown field 'payload'") as caught:
        AuthorityIR.from_json(json.dumps(payload))
    assert "secret-value" not in str(caught.value)
    with pytest.raises(IRFormatError, match="not valid JSON"):
        AuthorityIR.from_json(None)  # type: ignore[arg-type]


def test_reader_checks_optional_digest_and_review_types() -> None:
    payload = _from_mandate(
        loads("agent: a\ntools: [{name: t, effect: read}]\n")
    ).as_dict()
    payload["sources"][0]["content_sha256"] = 7
    with pytest.raises(IRFormatError, match="content_sha256 must be a string or null"):
        AuthorityIR.from_json(json.dumps(payload))

    payload = _from_mandate(
        loads("agent: a\ntools: [{name: t, effect: read}]\n")
    ).as_dict()
    payload["facts"][0]["evidence"][0]["review"] = "secret-value"
    with pytest.raises(IRFormatError, match="review has an invalid value") as caught:
        AuthorityIR.from_json(json.dumps(payload))
    assert "secret-value" not in str(caught.value)
