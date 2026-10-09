import hashlib
import json
import subprocess
import sys
from collections import Counter

import pytest

import agentmandate
import scripts.project_principal_observations as projection
from agentmandate._continuity import ContinuityFormatError
from agentmandate.cli import EXIT_USAGE, main

BASE = projection.BASE
ROOT = projection.ROOT


def _contents():
    return {BASE + name: (ROOT / BASE / name).read_bytes() for name in projection.PINS}


def test_principal_observations_preserve_principals_and_session_without_a_verdict():
    contents = _contents()
    record = projection.project_principal_observations(contents)
    assert projection.canonical_json(record) == projection.FIXTURE.read_text()
    assert record["evidence"] == {
        "confidence": "exact",
        "review": "unreviewed",
        "reviewer": None,
        "expires": None,
    }
    assert record["same_mandate"] is None
    assert record["mediation"] == "unestablished"
    assert record["monotonic_endpoints_retained"] is False
    assert (
        record["mandate_sha256"]
        == hashlib.sha256(
            (ROOT / "examples/continuity-refund/manifest.json").read_bytes()
        ).hexdigest()
    )
    assert len(record["sources"]) == 10
    for source in record["sources"]:
        assert source["content_sha256"] == hashlib.sha256(contents[source["locator"]]).hexdigest()
    events = json.loads(contents[record["events_locator"]])
    assert len(record["trials"]) == 20
    assert len({t["session_alias"] for t in record["trials"]}) == 20
    assert Counter(tuple(t["principal_sequence"]) for t in record["trials"]) == {
        ("a", "a"): 5,
        ("b", "b"): 5,
        ("a", "b"): 5,
        ("b", "a"): 5,
    }
    for trial in record["trials"]:
        source = events["trials"][int(trial["source_pointer"].split("/")[-1])]
        assert trial["session_alias"] == source["session_alias"]
        assert trial["session_relation"] == "recorded_same"
        first, second = trial["principal_sequence"]
        assert [c["principal_alias"] for c in trial["calls"]] == [first, second]
        assert [c["request_amount"] for c in trial["calls"]] == [600, 600]
        assert trial["observed_completed_by_principal"] == (
            {first: 600} if first == second else {"a": 600, "b": 600}
        )
        assert trial["observed_completed_across_principals"] == (600 if first == second else 1200)
        assert [c["outcome"] for c in trial["calls"]] == (
            ["allow", "deny"] if first == second else ["allow", "allow"]
        )
        assert not {"transition", "state", "admission", "safe_continuation"} & trial.keys()
    assert not {"state", "admission", "safe_continuation"} & record.keys()
    assert record["provider_state"]["completed"] == "unavailable"
    assert record["principal_identity_claim"]["raw_identifiers_retained"] is False
    assert len(record["single_request_controls"]) == 4
    assert not hasattr(agentmandate, "project_principal_observations")


def test_principal_clock_anomaly_is_retained_without_reconstructing_monotonic_endpoints():
    record = projection.project_principal_observations(_contents())
    anomalies = [
        c for row in record["trials"] for c in row["calls"] if c["wall_clock_delta_ms"] < 0
    ]
    assert len(anomalies) == 1
    assert anomalies[0]["wall_clock_delta_ms"] == -127.88
    assert anomalies[0]["recorded_duration_ms"] == 450.186783
    assert anomalies[0]["finished_at"] < anomalies[0]["started_at"]
    assert record["monotonic_endpoints_retained"] is False
    assert "not replayable here" in record["ordering_basis"]


@pytest.mark.parametrize("change", ["missing", "extra", "tampered"])
def test_principal_projection_requires_exact_pinned_bundle(change):
    contents = _contents()
    if change == "missing":
        contents.pop(BASE + "principal-continuity-events.json")
    elif change == "extra":
        contents["unreviewed.json"] = b"{}"
    else:
        contents[BASE + "principal-continuity-events.json"] += b" "
    with pytest.raises(ContinuityFormatError, match="source"):
        projection.project_principal_observations(contents)


def _reuse_identifier(raw):
    call = raw["trials"][0]["calls"][1]
    call["request"]["id"] = call["response"]["id"] = raw["trials"][0]["calls"][0]["request"]["id"]


@pytest.mark.parametrize(
    ("source", "mutate", "message"),
    [
        ("index", lambda r: r["sources"].pop(), "source join"),
        ("events", lambda r: r.update(mandate_sha256="0" * 64), "source join"),
        ("events", lambda r: r["principal_identity"].update(aliases=["a", "a"]), "configuration"),
        ("events", lambda r: r["provider_state"].update(consumed=0), "configuration"),
        ("deployment", lambda r: r["policies"][0].update(statement_sha256="0" * 64), "policy join"),
        ("events", lambda r: r["trials"].pop(), "trial identities"),
        ("events", lambda r: r["trials"].reverse(), "trial identities"),
        ("events", lambda r: r["trials"][1].update(principal_sequence=["a", "a"]), "relation"),
        ("events", lambda r: r["trials"][1].update(session_alias="other"), "relation"),
        ("events", lambda r: r["trials"][1]["calls"].pop(), "relation"),
        (
            "events",
            lambda r: r["trials"][1]["calls"][1].update(principal_alias="a"),
            "call identity",
        ),
        (
            "events",
            lambda r: r["trials"][0]["calls"][0]["request"]["params"]["arguments"].update(
                amount=400
            ),
            "call identity",
        ),
        (
            "events",
            lambda r: r["trials"][0]["calls"][0]["response"].update(id="wrong"),
            "call identity",
        ),
        (
            "events",
            lambda r: r["trials"][0]["calls"][0]["response"].update(error={}),
            "native allow",
        ),
        (
            "events",
            lambda r: r["trials"][0]["calls"][1]["response"]["error"].update(code=0),
            "denial",
        ),
        ("events", lambda r: r["trials"][0]["calls"][0].update(wall_clock_delta_ms=0), "clocks"),
        ("events", lambda r: r["trials"][0]["calls"][0].update(duration_ms=-1), "clocks"),
        ("events", lambda r: r["controls"].pop(), "single-request controls"),
        ("events", lambda r: r["controls"][0].update(session_alias="same-0"), "control session"),
        ("events", _reuse_identifier, "request identities"),
        (
            "summary",
            lambda r: r["results"].update(changed_principal_aggregate=600),
            "summary differs",
        ),
    ],
)
def test_principal_projection_rechecks_semantics_beyond_digest_pins(
    source, mutate, message, monkeypatch
):
    original = projection._migration_sources
    monkeypatch.setattr(
        projection,
        "_migration_sources",
        lambda contents, kinds, _: original(
            contents,
            kinds,
            {key: hashlib.sha256(value).hexdigest() for key, value in contents.items()},
        ),
    )
    contents = _contents()
    locator = BASE + f"principal-continuity-{source}.json"
    value = json.loads(contents[locator])
    mutate(value)
    contents[locator] = json.dumps(value).encode()
    with pytest.raises(ContinuityFormatError, match=message):
        projection.project_principal_observations(contents)


@pytest.mark.parametrize("command", ["validate", "reconcile"])
def test_observations_cannot_be_silently_consumed_as_a_runtime_profile(command, capsys):
    args = ["continuity", command]
    if command == "validate":
        args += [str(projection.FIXTURE)]
    else:
        args += [
            str(ROOT / "examples/continuity-refund/manifest.json"),
            "--continuity-provider",
            str(projection.FIXTURE),
            "--continuity-as-of",
            "2026-10-09T00:00:00Z",
            "--json",
        ]
    assert main(args) == EXIT_USAGE
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err


def test_principal_fixture_verifier_detects_derived_artifact_drift(tmp_path, monkeypatch):
    path = tmp_path / "observations.json"
    path.write_text(projection.FIXTURE.read_text() + " ")
    monkeypatch.setattr(projection, "FIXTURE", path)
    with pytest.raises(ContinuityFormatError, match="canonical observations"):
        projection.verify_fixture()


def test_principal_fixture_replays_through_repository_script():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/project_principal_observations.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "no continuity verdict" in result.stdout
