from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agentmandate._conditions import (
    GRANT_VERSION,
    ConditionContext,
    ConditionFormatError,
    Grant,
    ToolCondition,
    ToolPrincipal,
    _profile_digest,
    _validate_condition_profile,
    _validate_principal_profile,
)
from agentmandate._ir import AuthorityIR, Entity, Fact, _entity_id, _fact_id

FIXTURES = Path(__file__).parent / "fixtures"
CONTEXT = FIXTURES / "condition-context-select-v1.json"
CAPTURE = FIXTURES / "condition-context-capture.sql"
GRANT = FIXTURES / "delegation-grant-v1.json"
GRANT_CAPTURE = FIXTURES / "delegation-grant-capture.json"
CONDITION_STATEMENT = FIXTURES / "condition-statement-v1.json"
CONDITION_DISPATCH = FIXTURES / "condition-dispatch-v1.json"
PRINCIPAL_INTERSECTING = FIXTURES / "principal-intersecting-v1.json"
PRINCIPAL_FIXED = FIXTURES / "principal-fixed-user-v1.json"
PRINCIPAL_DELEGATED = FIXTURES / "principal-delegated-user-v1.json"
PROJECTION_DIGESTS = {
    CONDITION_STATEMENT: "eb7ae5abeb7fdfb4b9b7430320d434a62ce4f01de39f5d5d45c6402c8722e4f1",
    CONDITION_DISPATCH: "eefbf06e8779bf9d240325042e0099b9ce0eb40f38deaae84405673c97a4e58b",
    PRINCIPAL_FIXED: "21b1edd7d87175ddfe971577817a0b3ea3540c3f7b6c06e28357db2bd2052c29",
    PRINCIPAL_INTERSECTING: "e37c6c657b27b10c5418c85bf0cf62e872d89e12fddab8e78d50917b5d9c6b35",
    PRINCIPAL_DELEGATED: "249242e97cfdd8017a1b0e54c4284df94d1eb46af48516c4932ceae89d51a6f4",
}


def rehash_profile(graph: AuthorityIR) -> AuthorityIR:
    source = replace(
        graph.sources[0],
        semantic_sha256=_profile_digest(graph.entities, graph.facts, graph.edges),
    )
    return replace(graph, sources=(source, *graph.sources[1:]))


def test_canonical_context_fixture_round_trips_byte_stably():
    committed = CONTEXT.read_text(encoding="utf-8")
    value = ConditionContext.from_json(committed)
    reencoded = ConditionContext.from_json(value.to_json()).to_json()

    assert value.version == 1
    assert value.id == "contexts/aws-postgres/select-only"
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
    assert grant.grantor == "authorization-server:sentry"
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


@pytest.mark.parametrize(
    ("reviewer", "expires"),
    [
        ("platform-data", None),
        (None, "2027-01-01"),
        ("platform-data", "2027-01-01"),
    ],
)
def test_unreviewed_evidence_rejects_accountability_fields(reviewer, expires):
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    raw["evidence"] = {
        "confidence": "exact",
        "review": "unreviewed",
        **({"reviewer": reviewer} if reviewer is not None else {}),
        **({"expires": expires} if expires is not None else {}),
    }

    with pytest.raises(ConditionFormatError, match="while unreviewed"):
        ConditionContext.from_json(json.dumps(raw))


def test_unreviewed_evidence_without_accountability_fields_is_structurally_valid():
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    raw["evidence"] = {"confidence": "unknown", "review": "unreviewed"}

    parsed = ConditionContext.from_json(json.dumps(raw))

    assert parsed.evidence.reviewer is None
    assert parsed.evidence.expires is None


@pytest.mark.parametrize("field", ["scopes", "tools"])
def test_grant_surface_requires_every_authority_dimension(field):
    raw = json.loads(GRANT.read_text(encoding="utf-8"))
    del raw["surface"][field]

    with pytest.raises(ConditionFormatError, match=f"missing field '{field}'"):
        Grant.from_json(json.dumps(raw))


@pytest.mark.parametrize(
    ("field", "members"),
    [
        ("scopes", [""]),
        ("tools", [" update_issue"]),
        ("effects", ["read "]),
    ],
)
def test_grant_surface_members_must_be_nonempty_and_stripped(field, members):
    raw = json.loads(GRANT.read_text(encoding="utf-8"))
    raw["surface"][field] = members

    with pytest.raises(ConditionFormatError, match="non-empty and stripped"):
        Grant.from_json(json.dumps(raw))


@pytest.mark.parametrize(
    ("container", "field", "value"),
    [
        ("target", "source", ""),
        ("target", "source", "src\\server.py"),
        ("source", "locator", ""),
        ("source", "locator", "captures\\query.sql"),
    ],
)
def test_context_paths_must_be_nonempty_repository_relative_posix_paths(
    container, field, value
):
    raw = json.loads(CONTEXT.read_text(encoding="utf-8"))
    raw[container][field] = value

    with pytest.raises(ConditionFormatError, match="repository-relative POSIX path"):
        ConditionContext.from_json(json.dumps(raw))


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


@pytest.mark.parametrize("path", [CONDITION_STATEMENT, CONDITION_DISPATCH])
def test_tool_condition_fixtures_round_trip_and_project_canonically(path: Path):
    committed = path.read_text(encoding="utf-8")
    value = ToolCondition.from_json(committed)

    assert value.to_json() == committed
    graph = value.to_ir()
    assert AuthorityIR.from_json(graph.to_json()).to_json() == graph.to_json()
    assert {edge.relation for edge in graph.edges} == {
        "has_condition",
        "narrows_to",
        "uses_context",
    }
    assert {entity.kind for entity in graph.entities} == {
        "condition",
        "context",
        "effect",
        "tool",
    }
    assert all(fact.evidence[0].review == "accepted" for fact in graph.facts)


def test_statement_condition_addresses_the_reviewed_context_exactly():
    context = ConditionContext.from_json(CONTEXT.read_text(encoding="utf-8"))
    condition = ToolCondition.from_json(
        CONDITION_STATEMENT.read_text(encoding="utf-8")
    )

    assert condition.context == context.id
    assert (condition.target.source, condition.target.binding) == (
        context.target_source,
        context.target_binding,
    )
    assert condition.predicate == context.predicate
    assert condition.arg == context.arg
    assert condition.value_class in context.classes


@pytest.mark.parametrize(
    ("path", "relations"),
    [
        (PRINCIPAL_FIXED, {"acts_as"}),
        (PRINCIPAL_INTERSECTING, {"acts_as", "constrained_by"}),
        (PRINCIPAL_DELEGATED, {"acts_as", "under_grant"}),
    ],
)
def test_tool_principal_fixtures_round_trip_and_project_canonically(
    path: Path, relations: set[str]
):
    committed = path.read_text(encoding="utf-8")
    value = ToolPrincipal.from_json(committed)

    assert value.to_json() == committed
    graph = value.to_ir()
    assert AuthorityIR.from_json(graph.to_json()).to_json() == graph.to_json()
    assert {edge.relation for edge in graph.edges} == relations
    assert all(fact.evidence[0].confidence == "exact" for fact in graph.facts)


@pytest.mark.parametrize("path", sorted(PROJECTION_DIGESTS), ids=lambda path: path.stem)
def test_tool_record_projection_bytes_are_stable(path: Path):
    reader = ToolCondition if path.name.startswith("condition-") else ToolPrincipal
    graph = reader.from_json(path.read_text(encoding="utf-8")).to_ir()

    assert hashlib.sha256(graph.to_json().encode("utf-8")).hexdigest() == (
        PROJECTION_DIGESTS[path]
    )


def test_unreviewed_tool_record_stays_visible_without_accountability():
    raw = json.loads(CONDITION_STATEMENT.read_text(encoding="utf-8"))
    raw["evidence"] = {"confidence": "unknown", "review": "unreviewed"}

    graph = ToolCondition.from_json(json.dumps(raw)).to_ir()
    condition = next(entity for entity in graph.entities if entity.kind == "condition")
    facts = {(fact.subject, fact.predicate): fact for fact in graph.facts}

    assert facts[(condition.id, "reviewer")].value is None
    assert facts[(condition.id, "review_expires")].value is None
    assert all(fact.evidence[0].review == "unreviewed" for fact in graph.facts)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.update(condition_version=True),
        lambda raw: raw.update(condition_version=2),
        lambda raw: raw.update(id=""),
        lambda raw: raw.update(id=" condition"),
        lambda raw: raw["target"].update(source="../condition.json"),
        lambda raw: raw["target"].update(binding=""),
        lambda raw: raw["target"].update(tool=""),
        lambda raw: raw.update(predicate="argument_matches"),
        lambda raw: raw.update(effect="execute"),
        lambda raw: raw.update(effect="irreversible"),
        lambda raw: raw.update(arg=""),
        lambda raw: raw.update(**{"class": ""}),
        lambda raw: raw.update(context=""),
        lambda raw: raw.update(extra=True),
    ],
)
def test_tool_condition_reader_is_strict(mutate):
    raw = json.loads(CONDITION_STATEMENT.read_text(encoding="utf-8"))
    mutate(raw)

    with pytest.raises(ConditionFormatError):
        ToolCondition.from_json(json.dumps(raw))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.update(principal_version=False),
        lambda raw: raw.update(principal_version=2),
        lambda raw: raw.update(id=""),
        lambda raw: raw["target"].update(source="/absolute.py"),
        lambda raw: raw["principal"].update(kind="service"),
        lambda raw: raw["principal"].update(extra="value"),
        lambda raw: raw["principal"].update(principals=["one"]),
        lambda raw: raw["principal"].update(principals=["same", "same"]),
    ],
)
def test_intersecting_principal_reader_is_strict(mutate):
    raw = json.loads(PRINCIPAL_INTERSECTING.read_text(encoding="utf-8"))
    mutate(raw)

    with pytest.raises(ConditionFormatError):
        ToolPrincipal.from_json(json.dumps(raw))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["principal"].pop("actor"),
        lambda raw: raw["principal"].update(subject="user:invented"),
        lambda raw: raw["principal"].update(actor=""),
    ],
)
def test_fixed_principal_has_a_closed_field_set(mutate):
    raw = json.loads(PRINCIPAL_FIXED.read_text(encoding="utf-8"))
    mutate(raw)

    with pytest.raises(ConditionFormatError):
        ToolPrincipal.from_json(json.dumps(raw))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["principal"].pop("grant"),
        lambda raw: raw["principal"].update(principals=["one", "two"]),
        lambda raw: raw["principal"].update(expires="20261123"),
        lambda raw: raw["principal"].update(expires="2026-13-01"),
    ],
)
def test_delegated_principal_has_a_closed_typed_field_set(mutate):
    raw = json.loads(PRINCIPAL_DELEGATED.read_text(encoding="utf-8"))
    mutate(raw)

    with pytest.raises(ConditionFormatError):
        ToolPrincipal.from_json(json.dumps(raw))


def test_condition_profile_rejects_digest_predicate_and_relation_tampering():
    graph = ToolCondition.from_json(
        CONDITION_STATEMENT.read_text(encoding="utf-8")
    ).to_ir()
    with pytest.raises(ConditionFormatError, match="semantic digest"):
        _validate_condition_profile(
            replace(graph, sources=(replace(graph.sources[0], semantic_sha256="0" * 64),))
        )

    condition = next(entity for entity in graph.entities if entity.kind == "condition")
    changed = tuple(
        replace(fact, value="unknown")
        if fact.subject == condition.id and fact.predicate == "predicate"
        else fact
        for fact in graph.facts
    )
    changed_graph = replace(graph, facts=changed)
    changed_graph = replace(
        changed_graph,
        sources=(
            replace(
                graph.sources[0],
                semantic_sha256=_profile_digest(
                    changed_graph.entities, changed_graph.facts, changed_graph.edges
                ),
            ),
        ),
    )
    with pytest.raises(ConditionFormatError):
        _validate_condition_profile(changed_graph)


def test_principal_profile_rejects_structural_tampering():
    graph = ToolPrincipal.from_json(
        PRINCIPAL_INTERSECTING.read_text(encoding="utf-8")
    ).to_ir()
    with pytest.raises(ConditionFormatError, match="structurally invalid"):
        _validate_principal_profile(replace(graph, edges=graph.edges[1:]))


def test_intersection_rejects_fields_from_other_principal_kinds():
    raw = json.loads(PRINCIPAL_INTERSECTING.read_text(encoding="utf-8"))
    raw["principal"]["actor"] = "service:wrong-shape"

    with pytest.raises(ConditionFormatError, match="requires only principals"):
        ToolPrincipal.from_json(json.dumps(raw))


def test_condition_profile_rejects_extra_entities_and_target_mismatch():
    graph = ToolCondition.from_json(
        CONDITION_STATEMENT.read_text(encoding="utf-8")
    ).to_ir()
    extra = Entity(_entity_id("tool", "extra"), "tool", "extra")
    with pytest.raises(ConditionFormatError, match="unsupported entities"):
        _validate_condition_profile(
            rehash_profile(replace(graph, entities=graph.entities + (extra,)))
        )

    tool = next(entity for entity in graph.entities if entity.kind == "tool")
    facts = tuple(
        replace(fact, value={**fact.value, "tool": "other"})
        if fact.subject == tool.id and fact.predicate == "target"
        else fact
        for fact in graph.facts
    )
    with pytest.raises(ConditionFormatError, match="target does not match"):
        _validate_condition_profile(rehash_profile(replace(graph, facts=facts)))


def test_projection_source_is_closed_and_digest_bound():
    graph = ToolCondition.from_json(
        CONDITION_STATEMENT.read_text(encoding="utf-8")
    ).to_ir()
    extra_source = replace(graph.sources[0], id="source:extra")
    with pytest.raises(ConditionFormatError, match="requires one source"):
        _validate_condition_profile(
            replace(graph, sources=graph.sources + (extra_source,))
        )

    with pytest.raises(ConditionFormatError, match="unsupported source"):
        _validate_condition_profile(
            replace(graph, sources=(replace(graph.sources[0], adapter="other"),))
        )

    with pytest.raises(ConditionFormatError, match="source digest is invalid"):
        _validate_condition_profile(
            replace(graph, sources=(replace(graph.sources[0], content_sha256=None),))
        )


def test_projection_profile_rejects_fact_ambiguity():
    graph = ToolCondition.from_json(
        CONDITION_STATEMENT.read_text(encoding="utf-8")
    ).to_ir()
    condition = next(entity for entity in graph.entities if entity.kind == "condition")
    evidence = graph.facts[0].evidence
    unsupported = Fact(
        _fact_id(condition.id, "flavor"),
        condition.id,
        "flavor",
        "unknown",
        evidence,
    )
    with pytest.raises(ConditionFormatError, match="unsupported predicate"):
        _validate_condition_profile(
            rehash_profile(replace(graph, facts=graph.facts + (unsupported,)))
        )

    no_evidence = tuple(
        replace(fact, evidence=()) if fact.predicate == "arg" else fact
        for fact in graph.facts
    )
    with pytest.raises(ConditionFormatError, match="unsupported evidence"):
        _validate_condition_profile(rehash_profile(replace(graph, facts=no_evidence)))

    disagreement = tuple(
        replace(
            fact,
            evidence=(replace(fact.evidence[0], review="contested"),),
        )
        if fact.predicate == "arg"
        else fact
        for fact in graph.facts
    )
    with pytest.raises(ConditionFormatError, match="disagree on evidence"):
        _validate_condition_profile(rehash_profile(replace(graph, facts=disagreement)))

    wrong_name = tuple(
        replace(fact, value="wrong")
        if fact.subject == condition.id and fact.predicate == "name"
        else fact
        for fact in graph.facts
    )
    with pytest.raises(ConditionFormatError, match="entity name does not match"):
        _validate_condition_profile(rehash_profile(replace(graph, facts=wrong_name)))

    incomplete = tuple(fact for fact in graph.facts if fact.predicate != "arg")
    with pytest.raises(ConditionFormatError, match="profile is incomplete"):
        _validate_condition_profile(rehash_profile(replace(graph, facts=incomplete)))


def test_projection_profile_rechecks_review_accountability():
    graph = ToolCondition.from_json(
        CONDITION_STATEMENT.read_text(encoding="utf-8")
    ).to_ir()
    condition = next(entity for entity in graph.entities if entity.kind == "condition")
    facts = tuple(
        replace(fact, value=None)
        if fact.subject == condition.id and fact.predicate == "reviewer"
        else fact
        for fact in graph.facts
    )

    with pytest.raises(ConditionFormatError, match="requires a reviewer"):
        _validate_condition_profile(rehash_profile(replace(graph, facts=facts)))


def test_principal_profile_rejects_entity_root_kind_and_target_ambiguity():
    graph = ToolPrincipal.from_json(
        PRINCIPAL_FIXED.read_text(encoding="utf-8")
    ).to_ir()
    extra_kind = Entity(_entity_id("scope", "extra"), "scope", "extra")
    with pytest.raises(ConditionFormatError, match="unsupported entities"):
        _validate_principal_profile(
            rehash_profile(replace(graph, entities=graph.entities + (extra_kind,)))
        )

    without_kind = tuple(fact for fact in graph.facts if fact.predicate != "kind")
    with pytest.raises(ConditionFormatError, match="one structured principal"):
        _validate_principal_profile(
            rehash_profile(replace(graph, facts=without_kind))
        )

    extra_tool = Entity(_entity_id("tool", "extra"), "tool", "extra")
    with pytest.raises(ConditionFormatError, match="requires one tool"):
        _validate_principal_profile(
            rehash_profile(replace(graph, entities=graph.entities + (extra_tool,)))
        )

    root = next(entity for entity in graph.entities if entity.kind == "principal")
    invalid_kind = tuple(
        replace(fact, value="unknown")
        if fact.subject == root.id and fact.predicate == "kind"
        else fact
        for fact in graph.facts
    )
    with pytest.raises(ConditionFormatError, match="invalid kind"):
        _validate_principal_profile(
            rehash_profile(replace(graph, facts=invalid_kind))
        )

    tool = next(entity for entity in graph.entities if entity.kind == "tool")
    wrong_target = tuple(
        replace(fact, value={**fact.value, "tool": "other"})
        if fact.subject == tool.id and fact.predicate == "target"
        else fact
        for fact in graph.facts
    )
    with pytest.raises(ConditionFormatError, match="target does not match"):
        _validate_principal_profile(
            rehash_profile(replace(graph, facts=wrong_target))
        )


def test_intersection_profile_requires_two_exact_member_entities():
    graph = ToolPrincipal.from_json(
        PRINCIPAL_INTERSECTING.read_text(encoding="utf-8")
    ).to_ir()
    root = next(
        entity
        for entity in graph.entities
        if entity.kind == "principal" and entity.name.startswith("principals/")
    )
    members = [
        entity
        for entity in graph.entities
        if entity.kind == "principal" and entity.id != root.id
    ]
    removed, kept = members
    facts = tuple(
        replace(fact, value=[kept.id])
        if fact.subject == root.id and fact.predicate == "principals"
        else fact
        for fact in graph.facts
        if fact.subject != removed.id
    )
    edges = tuple(edge for edge in graph.edges if edge.target != removed.id)
    entities = tuple(entity for entity in graph.entities if entity.id != removed.id)
    with pytest.raises(ConditionFormatError, match="invalid intersection"):
        _validate_principal_profile(
            rehash_profile(replace(graph, entities=entities, facts=facts, edges=edges))
        )

    extra = Entity(_entity_id("principal", "extra"), "principal", "extra")
    name_fact = Fact(
        _fact_id(extra.id, "name"), extra.id, "name", "extra", graph.facts[0].evidence
    )
    with pytest.raises(ConditionFormatError, match="members do not match"):
        _validate_principal_profile(
            rehash_profile(
                replace(
                    graph,
                    entities=graph.entities + (extra,),
                    facts=graph.facts + (name_fact,),
                )
            )
        )


def test_delegated_profile_rechecks_expiry_and_grant_identity():
    graph = ToolPrincipal.from_json(
        PRINCIPAL_DELEGATED.read_text(encoding="utf-8")
    ).to_ir()
    root = next(entity for entity in graph.entities if entity.kind == "principal")
    bad_expiry = tuple(
        replace(fact, value="2026-13-01")
        if fact.subject == root.id and fact.predicate == "expires"
        else fact
        for fact in graph.facts
    )
    with pytest.raises(ConditionFormatError, match="invalid expiry"):
        _validate_principal_profile(rehash_profile(replace(graph, facts=bad_expiry)))

    extra = Entity(_entity_id("grant", "extra"), "grant", "extra")
    name_fact = Fact(
        _fact_id(extra.id, "name"), extra.id, "name", "extra", graph.facts[0].evidence
    )
    with pytest.raises(ConditionFormatError, match="grant does not match"):
        _validate_principal_profile(
            rehash_profile(
                replace(
                    graph,
                    entities=graph.entities + (extra,),
                    facts=graph.facts + (name_fact,),
                )
            )
        )


def test_fixed_principal_profile_rejects_a_grant_entity():
    graph = ToolPrincipal.from_json(PRINCIPAL_FIXED.read_text(encoding="utf-8")).to_ir()
    extra = Entity(_entity_id("grant", "extra"), "grant", "extra")
    name_fact = Fact(
        _fact_id(extra.id, "name"), extra.id, "name", "extra", graph.facts[0].evidence
    )

    with pytest.raises(ConditionFormatError, match="unexpected grant"):
        _validate_principal_profile(
            rehash_profile(
                replace(
                    graph,
                    entities=graph.entities + (extra,),
                    facts=graph.facts + (name_fact,),
                )
            )
        )
