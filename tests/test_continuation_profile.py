import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

import agentmandate
import scripts.migrate_continuity_evidence as projections
from agentmandate._continuity import (
    AgentCoreContinuity,
    ContinuityEvidence,
    ContinuityFormatError,
    ContinuityResult,
    analyse_continuity,
)
from agentmandate.cli import EXIT_FINDING, EXIT_OK, main
from agentmandate.manifest import load
from agentmandate.reach import analyse

ROOT = projections.ROOT
BASE = "docs/evidence/agentcore-refund-policy/"
FIXTURE = ROOT / "tests/fixtures/agentcore-continuation-v1.json"
ACCEPTED = ROOT / "docs/continuity-reviews/agentcore-continuation-2026-10-09.json"
MANIFEST = ROOT / "examples/continuity-refund/manifest.json"


def _contents():
    return {
        BASE + f"continuation-{name}.json": (ROOT / BASE / f"continuation-{name}.json").read_bytes()
        for name in ("protocol", "events", "deployment", "summary")
    }


def test_continuation_profile_preserves_all_six_arms_and_missing_recovery():
    contents = _contents()
    profile = projections.project_agentcore_continuation(contents)
    assert profile.to_json() == FIXTURE.read_text()
    assert AgentCoreContinuity.from_json(profile.to_json()) == profile
    profile.verify_sources(contents)
    assert profile.evidence.review == "unreviewed"
    assert profile.binding == "<reviewed-continuation-gateway>"
    assert profile.protocol == "MCP 2025-03-26"
    assert len(profile.controls) == 6
    assert sum(control.trials for control in profile.controls) == 60
    assert {control.same_mandate for control in profile.controls} == {None}
    assert {control.mediation for control in profile.controls} == {"unestablished"}
    by_id = {control.id: control for control in profile.controls}
    assert by_id["byte-identical-statement"].outcomes == ("allow", "stale_session")
    for name, control in by_id.items():
        assert control.revision_changed and control.boundary_changed
        assert control.intervals_overlap is False
        assert set(control.sources) == {source.id for source in profile.sources}
        assert control.trials == 10
        if name != "byte-identical-statement":
            assert control.outcomes == ("allow", "stale_session", "allow", "deny")
    assert by_id["tightening-to-700"].provider_limits == (1000, 700)
    assert by_id["tightening-to-700"].transition == "limit_revision"
    assert json.loads(contents[BASE + "continuation-protocol.json"])["mandate"]["sha256"] == (
        hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    )
    assert not hasattr(agentmandate, "project_agentcore_continuation")


@pytest.mark.parametrize("accepted", [False, True])
def test_continuation_profile_cannot_establish_a_mandate_binding(accepted):
    contents = _contents()
    profile = projections.project_agentcore_continuation(contents)
    if accepted:
        # Synthetic acceptance tests the remaining gap; never edit the real fixture.
        profile = replace(
            profile, evidence=ContinuityEvidence("exact", "accepted", "test-reviewer", "2027-01-01")
        )
    mandate = load(MANIFEST)
    result = analyse_continuity(
        mandate, profile, contents, as_of=datetime(2026, 10, 9, tzinfo=timezone.utc)
    )
    assert result.authority == analyse(mandate)
    assert {outcome.state for outcome in result.outcomes} == {"unresolved"}
    assert {outcome.admission for outcome in result.outcomes} == {"unresolved"}
    assert {outcome.safe_continuation for outcome in result.outcomes} == {"unresolved"}
    tightened = next(item for item in result.outcomes if item.transition == "tightening-to-700")
    assert tightened.authority_change == ("tightens" if accepted else "unresolved")
    assert tightened.completed_values == (1200,)
    assert not result.clean
    assert ContinuityResult.from_json(result.to_result().to_json()) == result.to_result()


@pytest.mark.parametrize("change", ["missing", "extra", "tampered"])
def test_continuation_projection_requires_the_exact_source_set(change):
    contents = _contents()
    if change == "missing":
        contents.pop(BASE + "continuation-events.json")
    elif change == "extra":
        contents["unreviewed.json"] = b"{}"
    else:
        contents[BASE + "continuation-events.json"] += b" "
    with pytest.raises(ContinuityFormatError, match="source"):
        projections.project_agentcore_continuation(contents)


@pytest.mark.parametrize(
    ("source", "mutate", "message"),
    [
        ("events", lambda raw: raw.update(mandate_sha256="0" * 64), "source join"),
        ("events", lambda raw: raw["trials"][0].update(arm="other"), "arms differ"),
        ("events", lambda raw: raw["trials"].pop(), "trial identities"),
        (
            "events",
            lambda raw: raw["trials"].append(raw["trials"][0]),
            "trial identities",
        ),
        ("events", lambda raw: raw["trials"][0].update(conforming=False), "trial control"),
        (
            "events",
            lambda raw: raw["trials"][0]["before_call"]["response"].update(error={"code": -32002}),
            "native decision",
        ),
        (
            "events",
            lambda raw: raw["trials"][0]["recovery_call"].update(session_alias="wrong"),
            "session or ordering",
        ),
        (
            "summary",
            lambda raw: raw["arms"]["tightening_to_700"].update(revision_changed=9),
            "summary differs",
        ),
    ],
)
def test_continuation_projection_checks_events_beyond_digest_identity(
    source, mutate, message, monkeypatch
):
    # Deliberately bypass the fixed pins to exercise the semantic joins as well.
    original = projections._migration_sources
    monkeypatch.setattr(
        projections,
        "_migration_sources",
        lambda contents, kinds, _: original(
            contents,
            kinds,
            {key: hashlib.sha256(value).hexdigest() for key, value in contents.items()},
        ),
    )
    contents = _contents()
    locator = BASE + f"continuation-{source}.json"
    raw = json.loads(contents[locator])
    mutate(raw)
    contents[locator] = json.dumps(raw).encode()
    with pytest.raises(ContinuityFormatError, match=message):
        projections.project_agentcore_continuation(contents)


def test_continuation_profile_works_through_existing_cli(capsys):
    assert main(["continuity", "validate", str(FIXTURE)]) == EXIT_OK
    capsys.readouterr()
    args = [
        "continuity", "reconcile", str(MANIFEST),
        "--continuity-provider", str(FIXTURE),
        "--continuity-as-of", "2026-10-09T00:00:00Z", "--json",
    ]
    for locator in _contents():
        args.extend(["--continuity-source", f"{locator}={ROOT / locator}"])
    assert main(args) == EXIT_FINDING
    output = capsys.readouterr()
    assert output.err == ""
    result = ContinuityResult.from_json(output.out)
    assert len(result.outcomes) == 6
    assert {item.safe_continuation for item in result.outcomes} == {"unresolved"}


def test_human_acceptance_only_changes_metadata_of_the_pinned_archival_profile():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == (
        "b22f056132e838aadaa7b5191b28f4a5c2fcc1ec8508d332c3d5f1f1df35c254"
    )
    archival = AgentCoreContinuity.from_json(FIXTURE.read_text())
    accepted = AgentCoreContinuity.from_json(ACCEPTED.read_text())
    assert accepted.to_json() == ACCEPTED.read_text()
    assert accepted == replace(
        archival, evidence=ContinuityEvidence("exact", "accepted", "mrwersa", "2026-11-08")
    )
    assert archival.evidence == ContinuityEvidence("exact", "unreviewed", None, None)
    accepted.verify_sources(_contents())


@pytest.mark.parametrize(
    ("as_of", "tampered", "eligible"),
    [
        ("2026-10-09T12:53:28+00:00", False, True),
        ("2026-11-08T23:59:59+00:00", False, True),
        ("2026-11-09T00:00:00+00:00", False, False),
        ("2026-10-09T12:53:28+00:00", True, False),
    ],
)
def test_accepted_observations_preserve_binding_gaps_expiry_and_source_checks(
    as_of, tampered, eligible
):
    profile = AgentCoreContinuity.from_json(ACCEPTED.read_text())
    contents = _contents()
    if tampered:
        contents[BASE + "continuation-events.json"] += b" "
    mandate = load(MANIFEST)
    result = analyse_continuity(
        mandate, profile, contents, as_of=datetime.fromisoformat(as_of)
    )
    assert result.authority == analyse(mandate)
    assert not result.clean
    assert len(result.outcomes) == 6
    for outcome in result.outcomes:
        assert outcome.state == "unresolved"
        assert outcome.admission == "unresolved"
        assert outcome.comparability == "unresolved"
        assert outcome.issuer_amendment == "unresolved"
        assert outcome.safe_continuation == "unresolved"
        assert outcome.completed_values == (
            (600,) if outcome.transition == "byte-identical-statement" else (1200,)
        )
        expected = "tightens" if outcome.transition == "tightening-to-700" else "stable"
        assert outcome.authority_change == (expected if eligible else "unresolved")
    codes = {finding.code for finding in result.findings}
    assert "continuity.state-reset" not in codes
    if tampered:
        assert "continuity.source-untrusted" in codes
    elif not eligible:
        assert "continuity.evidence-untrusted" in codes
    else:
        assert "continuity.evidence-untrusted" not in codes
        assert "continuity.source-untrusted" not in codes
    assert ContinuityResult.from_json(result.to_result().to_json()) == result.to_result()


def test_accepted_profile_cli_still_exits_with_unresolved_continuity(capsys):
    assert main(["continuity", "validate", str(ACCEPTED)]) == EXIT_OK
    capsys.readouterr()
    args = [
        "continuity", "reconcile", str(MANIFEST),
        "--continuity-provider", str(ACCEPTED),
        "--continuity-as-of", "2026-10-09T12:53:28Z", "--json",
    ]
    for locator in _contents():
        args.extend(["--continuity-source", f"{locator}={ROOT / locator}"])
    assert main(args) == EXIT_FINDING
    output = capsys.readouterr()
    assert output.err == ""
    result = ContinuityResult.from_json(output.out)
    assert {item.safe_continuation for item in result.outcomes} == {"unresolved"}
    assert {item.authority_change for item in result.outcomes} == {"stable", "tightens"}
