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
FIXTURE = ROOT / "tests/fixtures/agentcore-retransmission-v1.json"
MANIFEST = ROOT / "examples/continuity-refund/manifest.json"


def _contents():
    return {
        BASE + f"retry-continuity-{name}.json":
            (ROOT / BASE / f"retry-continuity-{name}.json").read_bytes()
        for name in ("contract", "events", "deployment", "summary")
    }


def test_retransmission_profile_preserves_repeated_completed_execution_only():
    contents = _contents()
    profile = projections.project_agentcore_retransmission(contents)
    assert profile.to_json() == FIXTURE.read_text()
    assert AgentCoreContinuity.from_json(profile.to_json()) == profile
    profile.verify_sources(contents)
    assert profile.evidence == ContinuityEvidence("exact", "unreviewed", None, None)
    assert profile.binding == "<reviewed-retry-continuity-gateway>"
    assert profile.protocol == "MCP (version not captured)"
    assert [c.id for c in profile.controls] == [
        "fresh-id-completed-prefix", "same-id-completed-prefix",
    ]
    for control in profile.controls:
        assert control.trials == 10
        assert control.transition == "same_boundary"
        assert control.outcomes == ("allow", "allow")
        assert control.request_amount == 400
        assert control.provider_limits == (1000,)
        assert control.same_mandate is None
        assert control.revision_changed is False
        assert control.boundary_changed is False
        assert control.intervals_overlap is None
        assert control.mediation == "unestablished"
        assert set(control.sources) == {s.id for s in profile.sources}
    events = json.loads(contents[BASE + "retry-continuity-events.json"])
    assert events["mandate_sha256"] == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    # The denied 300 probe is checked and retained in the source, never converted
    # to a fictitious 400-unit denial by the constant-amount profile.
    assert all(t["calls"][2]["request"]["params"]["arguments"]["amount"] == 300
               for t in events["trials"])
    assert not hasattr(agentmandate, "project_agentcore_retransmission")


def test_clock_anomaly_stays_in_source_without_an_interval_claim():
    contents = _contents()
    events = json.loads(contents[BASE + "retry-continuity-events.json"])
    anomalies = [(t["arm"], t["index"], index) for t in events["trials"]
                 for index, call in enumerate(t["calls"])
                 if call["finished_at"] < call["started_at"]]
    assert anomalies == [("same_id", 6, 1)]
    profile = projections.project_agentcore_retransmission(contents)
    assert all(c.intervals_overlap is None for c in profile.controls)


@pytest.mark.parametrize("state", ["unreviewed", "accepted", "expired", "tampered"])
def test_retransmission_counts_both_executions_without_establishing_continuity(state):
    contents = _contents()
    profile = projections.project_agentcore_retransmission(contents)
    if state != "unreviewed":
        # Synthetic trust variants do not accept or modify the archival fixture.
        profile = replace(profile, evidence=ContinuityEvidence(
            "exact", "accepted", "test-reviewer",
            "2026-10-08" if state == "expired" else "2027-01-01",
        ))
    if state == "tampered":
        contents[BASE + "retry-continuity-events.json"] += b" "
    mandate = load(MANIFEST)
    result = analyse_continuity(
        mandate, profile, contents, as_of=datetime(2026, 10, 9, tzinfo=timezone.utc)
    )
    assert result.authority == analyse(mandate)
    assert not result.clean
    assert len(result.outcomes) == 2
    for outcome in result.outcomes:
        # Two completed calls, not one deduplicated request and not 1,100 of
        # completed work (the final 300 was refused). Trials are not multiplied.
        assert outcome.completed_values == (800,)
        assert outcome.state == "unresolved"
        assert outcome.safe_continuation == "unresolved"
        assert outcome.authority_change == ("stable" if state == "accepted" else "unresolved")
        assert outcome.admission == ("within_bound" if state == "accepted" else "unresolved")
        assert next(a for a in outcome.alignments if a.check == "derivation_integrity").status == (
            "unresolved"
        )
    assert not {"continuity.state-reset", "continuity.state-preserved"} & {
        f.code for f in result.findings
    }
    assert ContinuityResult.from_json(result.to_result().to_json()) == result.to_result()


@pytest.mark.parametrize("change", ["missing", "extra", "tampered"])
def test_retransmission_projection_requires_pinned_sources(change):
    contents = _contents()
    if change == "missing":
        contents.pop(BASE + "retry-continuity-events.json")
    elif change == "extra":
        contents["unreviewed.json"] = b"{}"
    else:
        contents[BASE + "retry-continuity-events.json"] += b" "
    with pytest.raises(ContinuityFormatError, match="source"):
        projections.project_agentcore_retransmission(contents)


@pytest.mark.parametrize(("source", "mutate", "message"), [
    ("events", lambda r: r.update(mandate_sha256="0" * 64), "configuration or scope"),
    ("contract", lambda r: r["experiment"].update(ambiguous_timeout_simulated=True), "scope"),
    ("deployment", lambda r: r["gateway"].update(policy_engine_mode="LOG_ONLY"), "scope"),
    ("events", lambda r: r["trials"].pop(), "trial identities"),
    ("events", lambda r: r["trials"].append(r["trials"][0]), "trial identities"),
    ("events", lambda r: r["trials"][2].update(index=1), "trial identities"),
    ("events", lambda r: r["trials"][0]["calls"].pop(), "trial shape"),
    ("events", lambda r: r["trials"][0]["calls"][0].update(request_sha256="0" * 64), "identity"),
    ("events", lambda r: r["trials"][0]["calls"][0].update(duration_ms=-1), "identity"),
    ("events", lambda r: r["trials"][0]["calls"][0]["response"].update(id="other"), "identity"),
    ("events", lambda r: r["trials"][0]["calls"][2]["request"]["params"]["arguments"].update(
        amount=400), "identity"),
    ("events", lambda r: r["trials"][0]["calls"][0]["response"].update(error={}), "execution"),
    ("events", lambda r: r["trials"][0]["calls"][0].update(execution_alias=None), "execution"),
    ("events", lambda r: r["trials"][0]["calls"][2]["response"]["error"].update(code=0), "denial"),
    # Swap two intact native calls: identity checks pass, arm relation must not.
    ("events", lambda r: r["trials"][0]["calls"].__setitem__(1, r["trials"][1]["calls"][1]),
     "identifier relation"),
    ("events", lambda r: r["trials"][0]["calls"].__setitem__(1, r["trials"][0]["calls"][0]),
     "markers are not distinct"),
    ("events", lambda r: r["controls"].pop(), "single-request controls"),
    ("events", lambda r: r["controls"][0].update(amount=400), "single-request controls"),
    ("summary", lambda r: r["same_id"].update(distinct_second_executions=9), "summary differs"),
])
def test_retransmission_projection_rechecks_native_evidence(source, mutate, message, monkeypatch):
    # Bypass fixed digest pins only here to test the semantic checks independently.
    original = projections._migration_sources
    monkeypatch.setattr(projections, "_migration_sources", lambda contents, kinds, _: original(
        contents, kinds,
        {key: hashlib.sha256(value).hexdigest() for key, value in contents.items()},
    ))
    contents = _contents()
    locator = BASE + f"retry-continuity-{source}.json"
    raw = json.loads(contents[locator])
    mutate(raw)
    contents[locator] = json.dumps(raw).encode()
    with pytest.raises(ContinuityFormatError, match=message):
        projections.project_agentcore_retransmission(contents)


def test_retransmission_profile_cli_preserves_findings_and_completed_amount(capsys):
    assert main(["continuity", "validate", str(FIXTURE)]) == EXIT_OK
    capsys.readouterr()
    args = ["continuity", "reconcile", str(MANIFEST),
            "--continuity-provider", str(FIXTURE),
            "--continuity-as-of", "2026-10-09T00:00:00Z", "--json"]
    for locator in _contents():
        args.extend(["--continuity-source", f"{locator}={ROOT / locator}"])
    assert main(args) == EXIT_FINDING
    output = capsys.readouterr()
    assert output.err == ""
    result = ContinuityResult.from_json(output.out)
    assert len(result.outcomes) == 2
    assert {item.completed_values for item in result.outcomes} == {(800,)}
    assert {item.safe_continuation for item in result.outcomes} == {"unresolved"}
