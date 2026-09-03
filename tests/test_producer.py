from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

import agentmandate._producer as producer
from agentmandate._producer import (
    ProducerBoundary,
    ProducerBoundaryFormatError,
    ProducerEvidence,
    _captured,
    _digest,
    _integer,
    _load,
    _path,
    _pointer,
    _record,
    _string,
    _strings,
    migrate_aws_iam_access_key_boundary,
)

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "aws-iam-access-keys"
FIXTURE = ROOT / "tests" / "fixtures" / "producer-boundary-iam-v1.json"


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


def _encoded(raw: object) -> str:
    return json.dumps(raw, separators=(",", ":"))


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
