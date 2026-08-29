from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agentmandate import analyse, load, loads
from agentmandate._ir import AuthorityIR, _analyse_ir, _from_mandate, _to_mandate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_MANIFESTS = tuple(sorted((ROOT / "examples").glob("*.yaml")))
EVIDENCE_MANIFESTS = tuple(sorted((ROOT / "docs" / "evidence").glob("*/mandate.yaml")))
COMPATIBILITY = ROOT / "tests" / "fixtures" / "manifest-v1-shorthand-defaults.yaml"
ALL_DEFAULTS = ROOT / "tests" / "fixtures" / "manifest-v1-all-defaults.yaml"
MIGRATION = ROOT / "tests" / "fixtures" / "authority-ir-v1.json"


@pytest.mark.parametrize("path", EXAMPLE_MANIFESTS + EVIDENCE_MANIFESTS, ids=lambda p: p.stem)
def test_every_example_and_real_evidence_graph_round_trips(path: Path) -> None:
    content = path.read_bytes()
    mandate = load(path)
    snapshot = AuthorityIR.from_json(_from_mandate(mandate, content).to_json())
    restored = _to_mandate(snapshot)

    assert restored == mandate
    assert analyse(restored).as_dict() == analyse(mandate).as_dict()
    assert _analyse_ir(snapshot).authority.as_dict() == analyse(mandate).as_dict()
    source = next(item for item in snapshot.sources if item.id == "source:mandate")
    assert source.content_sha256 == hashlib.sha256(content).hexdigest()


def test_the_matrix_is_all_examples_and_six_independent_graphs() -> None:
    assert {path.name for path in EXAMPLE_MANIFESTS} == {
        "dispute-resolver-sod.yaml",
        "dispute-resolver-v2.yaml",
        "dispute-resolver.yaml",
    }
    assert {path.parent.name for path in EVIDENCE_MANIFESTS} == {
        "agentkit",
        "agentcore-refund-policy",
        "aws-postgres-mcp",
        "github-mcp-server",
        "initiative-mcp",
        "sentry-mcp",
    }


def test_shorthands_and_omitted_defaults_have_schema_provenance() -> None:
    content = COMPATIBILITY.read_bytes()
    source = "tests/fixtures/manifest-v1-shorthand-defaults.yaml"
    mandate = loads(content.decode(), source=source)
    snapshot = _from_mandate(mandate, content)
    restored = _to_mandate(AuthorityIR.from_json(snapshot.to_json()))
    facts = {(item.subject, item.predicate): item for item in snapshot.facts}

    assert restored == mandate
    assert mandate.identity is None
    assert mandate.roles == {"reviewer": ("inspect_case",)}
    assert mandate.tools[0].requires == ("case",)
    assert mandate.tools[1].requires == ()
    assert mandate.limits.depth == 8
    assert mandate.limits.total is None
    assert mandate.limits.effects == {}
    defaults_source = next(
        item for item in snapshot.sources if item.id == "source:manifest-v1"
    )
    assert defaults_source.format_version == 1

    defaulted = {
        ("agent:compatibility%2Fdefaults", "identity"),
        ("constraint:run", "depth"),
        ("constraint:run", "effects"),
        ("constraint:run", "total"),
        ("tool:get_status", "ceiling"),
        ("tool:get_status", "principal"),
        ("tool:get_status", "produces"),
        ("tool:get_status", "requires"),
        ("tool:get_status", "requires_approval"),
        ("tool:get_status", "scope_key"),
        ("tool:get_status", "unbounded"),
        ("tool:get_status", "value_arg"),
    }
    assert all(
        any(evidence.source == "source:manifest-v1" for evidence in facts[key].evidence)
        for key in defaulted
    )

    defaults_content = ALL_DEFAULTS.read_bytes()
    defaults = _from_mandate(
        loads(defaults_content.decode(), source="tests/fixtures/manifest-v1-all-defaults.yaml"),
        defaults_content,
    )
    roles = next(
        item
        for item in defaults.facts
        if item.subject == "agent:all-defaults" and item.predicate == "roles"
    )
    assert roles.value == []
    assert any(evidence.source == "source:manifest-v1" for evidence in roles.evidence)


def test_canonical_v1_migration_fixture_remains_readable_and_reproducible() -> None:
    content = COMPATIBILITY.read_bytes()
    mandate = loads(
        content.decode(), source="tests/fixtures/manifest-v1-shorthand-defaults.yaml"
    )
    committed = MIGRATION.read_text(encoding="utf-8")

    assert _from_mandate(mandate, content).to_json() == committed
    assert _to_mandate(AuthorityIR.from_json(committed)) == mandate
