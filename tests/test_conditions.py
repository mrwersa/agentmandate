from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmandate._conditions import (
    GRANT_VERSION,
    ConditionContext,
    ConditionFormatError,
    Grant,
)

FIXTURES = Path(__file__).parent / "fixtures"
CONTEXT = FIXTURES / "condition-context-select-v1.json"
CAPTURE = FIXTURES / "condition-context-capture.sql"
GRANT = FIXTURES / "delegation-grant-v1.json"
GRANT_CAPTURE = FIXTURES / "delegation-grant-capture.json"


def test_canonical_context_fixture_round_trips_byte_stably():
    committed = CONTEXT.read_text(encoding="utf-8")
    value = ConditionContext.from_json(committed)
    reencoded = ConditionContext.from_json(value.to_json()).to_json()

    assert value.version == 1
    assert value.to_json() == committed
    assert reencoded == committed
    assert value.target_binding == "run_query"
    assert value.classes == ("ddl", "dml", "select-only")
    assert value.dialect == "postgresql-16"
    assert value.source is not None
    assert value.source.kind == "argument-capture"


def test_context_verifies_the_committed_capture_bytes():
    value = ConditionContext.from_json(CONTEXT.read_text(encoding="utf-8"))

    value.verify_source(CAPTURE.read_bytes())
    with pytest.raises(ConditionFormatError, match="does not match"):
        value.verify_source(b"DROP ALL")


def test_verify_source_rejects_non_bytes_without_leaking_types():
    value = ConditionContext.from_json(CONTEXT.read_text(encoding="utf-8"))

    with pytest.raises(ConditionFormatError, match="requires bytes"):
        value.verify_source("SELECT 1;\n")  # type: ignore[arg-type]


def test_a_context_without_a_capture_digest_has_nothing_to_verify():
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    del raw["source"]["content_sha256"]
    value = ConditionContext.from_json(json.dumps(raw))

    with pytest.raises(ConditionFormatError, match="no content digest"):
        value.verify_source(b"")


def test_canonical_grant_fixture_round_trips_byte_stably():
    committed = GRANT.read_text(encoding="utf-8")
    grant = Grant.from_json(committed)
    reencoded = Grant.from_json(grant.to_json()).to_json()

    assert grant.version == GRANT_VERSION
    assert grant.subject == "user:ada"
    assert grant.actor.startswith("spiffe://")
    assert grant.scopes == ("issue:write", "project:read")
    assert grant.tools == ("find_projects", "update_issue")
    assert grant.effects == ("read", "write")
    assert reencoded == committed


def test_grant_verifies_the_committed_exchange_bytes():
    grant = Grant.from_json(GRANT.read_text(encoding="utf-8"))

    grant.verify_source(GRANT_CAPTURE.read_bytes())
    with pytest.raises(ConditionFormatError, match="does not match"):
        grant.verify_source(b"{}")


def test_surface_members_are_canonicalized_and_deduplication_is_rejected():
    raw = json.loads(GRANT.read_text(encoding="utf-8"))
    raw["surface"]["scopes"] = ["project:read", "issue:write", "project:read"]

    with pytest.raises(ConditionFormatError, match="duplicate members"):
        Grant.from_json(json.dumps(raw))

    raw["surface"]["scopes"] = ["issue:write", "project:read"]
    parsed = Grant.from_json(json.dumps(raw))
    assert parsed.scopes == ("issue:write", "project:read")


def test_context_classes_are_canonicalized_and_deduplication_is_rejected():
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    raw["domain"]["classes"] = ["select-only", "dml", "dml"]

    with pytest.raises(ConditionFormatError, match="duplicate members"):
        ConditionContext.from_json(json.dumps(raw))

    raw["domain"]["classes"] = ["select-only", "dml"]
    parsed = ConditionContext.from_json(json.dumps(raw))
    assert parsed.classes == ("dml", "select-only")


def test_records_are_frozen_after_construction():
    context = ConditionContext.from_json(CONTEXT.read_text(encoding="utf-8"))
    grant = Grant.from_json(GRANT.read_text(encoding="utf-8"))

    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.classes = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        grant.subject = "user:bob"  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(context_version=2),
        lambda d: d.update(context_version=True),
        lambda d: d.update(context_version="one"),
        lambda d: d["target"].update(source="/absolute/path.py"),
        lambda d: d["target"].update(source="../escape.py"),
        lambda d: d["target"].update(binding=""),
        lambda d: d["domain"].update(predicate="argument_matches"),
        lambda d: d["domain"].pop("classifier"),
        lambda d: d["domain"].update(classifier=""),
        lambda d: d["domain"].pop("classifier_version"),
        lambda d: d["domain"].update(classifier_version=3),
        lambda d: d["domain"].update(classes=[]),
        lambda d: d["domain"].update(classes=["select-only", 5]),
        lambda d: d.update(completeness="complete-ish"),
        lambda d: d["evidence"].update(expires="20260801"),
        lambda d: d["evidence"].update(expires="2026-13-40"),
        lambda d: d["evidence"].pop("expires"),
        lambda d: d.pop("evidence"),
        lambda d: d["source"].update(content_sha256="abc"),
        lambda d: d["source"].update(locator="/abs.jsonl"),
        lambda d: d.update(surprise=1),
        lambda d: d.pop("target"),
    ],
)
def test_strict_reader_rejects_malformed_contexts(mutate):
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    mutate(raw)

    with pytest.raises(ConditionFormatError):
        ConditionContext.from_json(json.dumps(raw))


def test_statement_class_requires_a_dialect_and_dispatch_target_does_not():
    statement = json.loads(CONTEXT.read_text(encoding="utf-8"))
    del statement["domain"]["dialect"]

    with pytest.raises(ConditionFormatError, match="required for statement_class"):
        ConditionContext.from_json(json.dumps(statement))

    dispatch = json.loads(CONTEXT.read_text(encoding="utf-8"))
    dispatch["domain"]["predicate"] = "dispatch_target"
    dispatch["domain"]["classes"] = ["find_projects"]
    del dispatch["domain"]["dialect"]
    parsed = ConditionContext.from_json(json.dumps(dispatch))
    assert parsed.predicate == "dispatch_target"
    assert parsed.dialect is None


def test_version_type_errors_do_not_echo_the_value():
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    raw["context_version"] = "one"

    with pytest.raises(ConditionFormatError) as excinfo:
        ConditionContext.from_json(json.dumps(raw))
    assert "'one'" not in str(excinfo.value)

    grant_raw = json.loads(GRANT.read_text(encoding="utf-8"))
    grant_raw["grant_version"] = {"v": 2}

    with pytest.raises(ConditionFormatError) as excinfo:
        Grant.from_json(json.dumps(grant_raw))
    message = str(excinfo.value)
    assert "'{ \"v\": 2 }'" not in message and "{\"v\": 2}" not in message


def test_reviewer_and_expiry_stand_or_fall_together():
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    raw["evidence"] = {"confidence": "exact", "review": "accepted", "reviewer": "x"}

    with pytest.raises(ConditionFormatError, match="requires a reviewer and an expiry"):
        ConditionContext.from_json(json.dumps(raw))

    raw["evidence"] = {"confidence": "exact", "review": "accepted", "expires": "2027-01-01"}
    with pytest.raises(ConditionFormatError, match="requires a reviewer and an expiry"):
        ConditionContext.from_json(json.dumps(raw))

    raw["evidence"]["reviewer"] = "platform-data"
    parsed = ConditionContext.from_json(json.dumps(raw))
    assert parsed.evidence.reviewer == "platform-data"


def test_contested_evidence_parses_but_is_marked_for_gate3():
    """Contested evidence is structurally valid; eligibility is analysis work."""
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    raw["evidence"]["review"] = "contested"
    value = ConditionContext.from_json(json.dumps(raw))

    assert value.evidence.review == "contested"


def test_temporal_ordering_and_identity_edges_are_typed():
    grant_dict = json.loads(GRANT.read_text(encoding="utf-8"))
    raw = dict(grant_dict)
    raw["issued"], raw["expires"] = raw["expires"], "2026-07-01"

    with pytest.raises(ConditionFormatError, match="must not be after"):
        Grant.from_json(json.dumps(raw))

    for field in ("subject", "actor", "audience", "id"):
        broken = dict(grant_dict)
        broken[field] = ""
        with pytest.raises(ConditionFormatError, match="must not be empty"):
            Grant.from_json(json.dumps(broken))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(grant_version=3),
        lambda d: d["surface"].update(effects=["execute"]),
        lambda d: d["surface"].update(effects=[]),
        lambda d: d["surface"].update(scopes="project:read"),
        lambda d: d.update(expires="not-a-date"),
        lambda d: d.update(expires="20260801"),
        lambda d: d.update(issued=None),
        lambda d: d.update(extra=1),
        lambda d: d["source"].update(kind=""),
    ],
)
def test_strict_reader_rejects_malformed_grants(mutate):
    raw = json.loads(GRANT.read_text(encoding="utf-8"))
    mutate(raw)

    with pytest.raises(ConditionFormatError):
        Grant.from_json(json.dumps(raw))


def test_reader_rejects_invalid_json_nan_and_non_object_roots():
    with pytest.raises(ConditionFormatError, match="not valid JSON"):
        ConditionContext.from_json("{broken")
    with pytest.raises(ConditionFormatError, match="non-canonical value"):
        ConditionContext.from_json('{"target": NaN}')
    with pytest.raises(ConditionFormatError, match="must be an object"):
        Grant.from_json("42")
    with pytest.raises(ConditionFormatError, match="not valid JSON"):
        Grant.from_json("")


def test_grant_evidence_and_surface_type_edges_are_typed():
    grant_dict = json.loads(GRANT.read_text(encoding="utf-8"))

    for field, bad in (
        ("confidence", None),
        ("review", 9),
        ("confidence", "vibes"),
        ("review", "maybe"),
    ):
        broken = json.loads(json.dumps(grant_dict))
        if bad is None:
            broken["evidence"][field] = None
        else:
            broken["evidence"][field] = bad
        with pytest.raises(ConditionFormatError):
            Grant.from_json(json.dumps(broken))

    broken = json.loads(json.dumps(grant_dict))
    broken["evidence"]["reviewer"] = ["team"]
    with pytest.raises(ConditionFormatError, match="reviewer must be a string"):
        Grant.from_json(json.dumps(broken))

    broken = json.loads(json.dumps(grant_dict))
    broken["source"]["producer_version"] = [1]
    with pytest.raises(
        ConditionFormatError, match="producer_version must be a string or null"
    ):
        Grant.from_json(json.dumps(broken))

    broken = json.loads(json.dumps(grant_dict))
    broken["surface"]["effects"] = []
    with pytest.raises(ConditionFormatError, match="members must be non-empty"):
        Grant.from_json(json.dumps(broken))


def test_context_source_and_dialect_edges_are_typed():
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))

    broken = json.loads(json.dumps(raw))
    broken["domain"]["dialect"] = ""
    with pytest.raises(ConditionFormatError, match="dialect must not be empty"):
        ConditionContext.from_json(json.dumps(broken))

    dispatch_no_dialect = json.loads(json.dumps(raw))
    dispatch_no_dialect["domain"]["predicate"] = "dispatch_target"
    dispatch_no_dialect["domain"]["classes"] = ["find_projects"]
    del dispatch_no_dialect["domain"]["dialect"]
    parsed = ConditionContext.from_json(json.dumps(dispatch_no_dialect))
    assert parsed.dialect is None

    broken = json.loads(json.dumps(raw))
    broken["source"]["producer_version"] = [2]
    with pytest.raises(
        ConditionFormatError, match="producer_version must be a string or null"
    ):
        ConditionContext.from_json(json.dumps(broken))


def test_grant_verify_source_requires_bytes_or_a_digest():
    grant = Grant.from_json(GRANT.read_text(encoding="utf-8"))

    with pytest.raises(ConditionFormatError, match="requires bytes"):
        grant.verify_source("{}")  # type: ignore[arg-type]

    bare = dict(grant.as_dict())
    bare.pop("source")
    stripped = Grant.from_json(json.dumps(bare))
    with pytest.raises(ConditionFormatError, match="no content digest"):
        stripped.verify_source(b"{}")


def test_context_verify_source_requires_bytes_or_a_digest():
    context = ConditionContext.from_json(CONTEXT.read_text(encoding="utf-8"))

    with pytest.raises(ConditionFormatError, match="requires bytes"):
        context.verify_source("sql")  # type: ignore[arg-type]

    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    raw.pop("source")
    stripped = ConditionContext.from_json(json.dumps(raw))
    with pytest.raises(ConditionFormatError, match="no content digest"):
        stripped.verify_source(b"SELECT 1;\n")


def test_context_dispatch_dialect_type_is_typed():
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    raw["domain"]["predicate"] = "dispatch_target"
    raw["domain"]["classes"] = ["find_projects"]
    raw["domain"]["dialect"] = 16

    with pytest.raises(ConditionFormatError, match="dialect must be a string"):
        ConditionContext.from_json(json.dumps(raw))


def test_grant_surface_rejects_empty_effects():
    raw = json.loads(GRANT.read_text(encoding="utf-8"))
    raw["surface"]["effects"] = []

    with pytest.raises(ConditionFormatError, match="members must be non-empty"):
        Grant.from_json(json.dumps(raw))
