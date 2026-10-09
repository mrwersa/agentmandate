import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentmandate._continuity import ContinuityFormatError
from agentmandate._principal_continuity import PrincipalContinuity, analyse_principal_continuity
from agentmandate.cli import main
from agentmandate.manifest import loads
from agentmandate.reach import analyse

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/principal-continuity"
AS_OF = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


def _raw():
    return json.loads((EXAMPLE / "profile.json").read_text())


def _run(raw=None, *, when=AS_OF, contents=None, depth=None):
    profile = PrincipalContinuity.from_json(json.dumps(_raw() if raw is None else raw))
    manifest = (EXAMPLE / "manifest.json").read_bytes()
    return analyse_principal_continuity(
        loads(manifest.decode()),
        profile,
        {"observations.json": (EXAMPLE / "observations.json").read_bytes()}
        if contents is None
        else contents,
        as_of=when,
        mandate_bytes=manifest,
        depth=depth,
    )


def test_three_boundaries_remain_distinct_and_no_observation_authorizes_shared_accounting():
    result = _run()
    assert result["schema"] == "agentmandate.principal-continuity/v1"
    assert result["observations_eligible"] is True
    trials = {trial["id"]: trial for trial in result["trials"]}
    changed = trials["changed-principal-same-session"]
    assert changed["relations"] == [{"principal": "changed", "session": "same"}]
    assert changed["observed_completed_by_principal"] == {"a": 600, "b": 600}
    same = trials["same-principal-same-session"]
    assert same["relations"] == [{"principal": "same", "session": "same"}]
    assert same["observed_completed_by_principal"] == {"a": 600}
    fresh = trials["same-principal-fresh-session"]
    assert fresh["relations"] == [{"principal": "same", "session": "changed"}]
    assert fresh["observed_completed_by_principal"] == {"a": 1200}
    for trial in trials.values():
        assert trial["completion_known"] is True
        for field in ("mandate_identity", "state", "admission", "safe_continuation"):
            assert trial[field] == "unresolved"
        assert "observed_completed_across_principals" not in trial
    assert [f["code"] for f in result["findings"]] == ["continuity.shared-mandate-unresolved"]
    assert result["authority"] == analyse(loads((EXAMPLE / "manifest.json").read_text())).as_dict()
    profile = PrincipalContinuity.from_json(json.dumps(_raw()))
    assert result["profile_sha256"] == hashlib.sha256(profile.to_json().encode()).hexdigest()
    assert (
        result["manifest_sha256"]
        == hashlib.sha256((EXAMPLE / "manifest.json").read_bytes()).hexdigest()
    )
    assert PrincipalContinuity.from_json(profile.to_json()).to_json() == profile.to_json()


def test_unknown_completion_session_and_order_are_not_inferred_from_native_allow():
    raw = _raw()
    raw["trials"][0]["ordering"] = "unknown"
    call = raw["trials"][0]["calls"][0]
    call.update(completion="unknown", session=None)
    result = _run(raw)
    trial = next(t for t in result["trials"] if t["id"] == raw["trials"][0]["id"])
    assert trial["ordering"] == "unknown"
    assert trial["calls"][0]["native_outcome"] == "allow"
    assert trial["completion_known"] is False
    assert trial["observed_completed_by_principal"] == {"a": 0}
    assert trial["relations"] == [{"principal": "same", "session": "unknown"}]


@pytest.mark.parametrize("state", ["unreviewed", "contested", "heuristic", "expired", "tampered"])
def test_evidence_gaps_cannot_become_eligible_observations(state):
    raw = _raw()
    contents = None
    if state == "unreviewed":
        raw["evidence"].update(review=state, reviewer=None, expires=None)
    elif state == "contested":
        raw["evidence"]["review"] = state
    elif state == "heuristic":
        raw["evidence"]["confidence"] = state
    elif state == "expired":
        raw["evidence"]["expires"] = "2026-10-08"
    else:
        contents = {"observations.json": b"tampered"}
    result = _run(raw, contents=contents)
    assert result["observations_eligible"] is False
    assert len(result["findings"]) == 2
    assert all(t["state"] == t["admission"] == "unresolved" for t in result["trials"])
    assert result["trials"][0]["observed_completed_by_principal"] == {"a": 600, "b": 600}


@pytest.mark.parametrize(
    ("when", "eligible"),
    [
        (datetime(2026, 11, 8, 23, 59, 59, tzinfo=timezone.utc), True),
        (datetime(2026, 11, 9, tzinfo=timezone.utc), False),
    ],
)
def test_expiry_is_inclusive_utc(when, eligible):
    assert _run(when=when)["observations_eligible"] is eligible


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(principal_continuity_version=2),
        lambda r: r.update(principal_continuity_version=True),
        lambda r: r.update(same_mandate=True),
        lambda r: r.update(continuity_binding_version=1),
        lambda r: r.update(principals=[]),
        lambda r: r.update(trials="not an array"),
        lambda r: r["principals"].append(r["principals"][0]),
        lambda r: r["principals"][0].update(sources=["missing"]),
        lambda r: r["trials"].append(r["trials"][0]),
        lambda r: r["trials"][0].update(ordering="retained_monotonic"),
        lambda r: r["trials"][0].update(ordering=[]),
        lambda r: r["trials"][0]["calls"].pop(),
        lambda r: r["trials"][0]["calls"][0].update(principal="missing"),
        lambda r: r["trials"][0]["calls"][0].update(source="missing"),
        lambda r: r["trials"][0]["calls"][0].update(amount=True),
        lambda r: r["trials"][0]["calls"][0].update(amount=-1),
        lambda r: r["trials"][0]["calls"][0].update(amount=0.5),
        lambda r: r["trials"][0]["calls"][0].update(session=""),
        lambda r: r["trials"][0]["calls"][0].update(completion="allow"),
        lambda r: r["trials"][0]["calls"][0].update(pointer="invalid"),
        lambda r: r["trials"][0]["calls"][0].update(pointer="/bad~2escape"),
        lambda r: r["trials"][0]["calls"].append(r["trials"][0]["calls"][0]),
        lambda r: r["trials"][1]["calls"].append(r["trials"][0]["calls"][0]),
        lambda r: r["measurement"].update(unit=""),
        lambda r: r["evidence"].update(expires=None),
    ],
)
def test_strict_contract_refuses_unsupported_or_ambiguous_records(mutate):
    raw = _raw()
    mutate(raw)
    with pytest.raises(ContinuityFormatError):
        PrincipalContinuity.from_json(json.dumps(raw))


def _args():
    return [
        "continuity",
        "reconcile",
        str(EXAMPLE / "manifest.json"),
        "--continuity-provider",
        str(EXAMPLE / "profile.json"),
        "--continuity-source",
        f"observations.json={EXAMPLE / 'observations.json'}",
        "--continuity-as-of",
        "2026-10-09T12:00:00Z",
    ]


def test_cli_validates_then_returns_complete_unresolved_json_and_text(capsys):
    assert main(["continuity", "validate", str(EXAMPLE / "profile.json")]) == 0
    assert capsys.readouterr().out == "valid principal continuity profile v1\n"
    assert main([*_args(), "--json"]) == 1
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out) == _run()
    assert main(_args()) == 1
    output = capsys.readouterr()
    assert "observations eligible: true" in output.out
    assert "changed-principal-same-session" in output.out
    assert "AUTHORITY" in output.out
    assert not output.err


@pytest.mark.parametrize(
    ("fixture", "as_of"),
    [
        ("eligible", "2026-10-09T12:00:00Z"),
        ("expired", "2026-11-09T00:00:00Z"),
    ],
)
def test_cli_preserves_released_v1_result_bytes(fixture, as_of, capsys):
    args = _args()
    args[-1] = as_of
    assert main([*args, "--json"]) == 1
    output = capsys.readouterr()
    assert not output.err
    expected = ROOT / "tests/fixtures" / f"principal-continuity-result-v1-{fixture}.json"
    assert output.out.encode("utf-8") == expected.read_bytes()


@pytest.mark.parametrize(
    "options",
    [
        ["--continuity-binding", "missing.json", "--continuity-binding-source", "x=missing.json"],
        ["--continuity-source", "extra=missing.json"],
        ["--ir"],
        ["--graph"],
    ],
)
def test_unsupported_composition_and_bindings_fail_without_partial_output(options, capsys):
    assert main([*_args(), *options, "--json"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


def test_cli_malformed_and_missing_sources_fail_without_partial_output(tmp_path, capsys):
    profile = tmp_path / "profile.json"
    raw = _raw()
    raw["trials"][0]["calls"][0]["completion"] = "invented"
    profile.write_text(json.dumps(raw))
    assert main([*_args(), "--continuity-provider", str(profile), "--json"]) == 2
    assert capsys.readouterr().out == ""
    args = _args()
    del args[5:7]
    assert main(args) == 2
    assert capsys.readouterr().out == ""


def test_explicit_depth_keeps_manifest_analysis_boundary():
    result = _run(depth=1)
    assert (
        result["authority"]
        == analyse(loads((EXAMPLE / "manifest.json").read_text()), depth=1).as_dict()
    )
