import hashlib
import json
import subprocess
import sys

import pytest

import scripts.audit_capture_clocks as clocks


def _contents():
    return {
        clocks.BASE + name: (clocks.ROOT / clocks.BASE / name).read_bytes()
        for name in clocks.SOURCES
    }


def test_pinned_clock_audit_counts_all_calls_and_retains_each_regression():
    report = clocks.audit(_contents())
    expected = clocks.ROOT / "tests/fixtures/capture-clock-audit-v1.json"
    assert report == json.loads(expected.read_text())
    assert report["totals"] == {
        "calls": 510,
        "retained_monotonic_pairs": 300,
        "utc_regressions": 6,
        "negative_monotonic_intervals": 0,
    }
    files = {f["locator"].removeprefix(clocks.BASE): f for f in report["files"]}
    principal = files["principal-continuity-events.json"]["utc_regressions"]
    retry = files["retry-continuity-events.json"]["utc_regressions"]
    continuation = files["continuation-events.json"]["utc_regressions"]
    assert [(r["wall_delta_us"], r["recorded_duration_ms"]) for r in principal] == [
        (-127880, 450.186783),
    ]
    assert principal[0]["outcome"] == "deny"
    assert [(r["wall_delta_us"], r["recorded_duration_ms"]) for r in retry] == [
        (-152115, 516.247859),
    ]
    assert principal[0]["monotonic_elapsed_ns"] is retry[0]["monotonic_elapsed_ns"] is None
    assert len(continuation) == 4
    assert all(r["monotonic_elapsed_ns"] > 0 for r in continuation)
    assert files["continuation-diagnostic-events.json"]["calls_with_monotonic_endpoints"] == 72
    # Zero UTC regressions does not imply replayable durations.
    assert files["temporal-transition-events.json"]["utc_regressions"] == []
    assert files["temporal-transition-events.json"]["calls_without_monotonic_endpoints"] == 100


@pytest.mark.parametrize("change", ["missing", "extra", "tampered"])
def test_clock_audit_requires_the_exact_source_set_and_bytes(change):
    contents = _contents()
    locator = clocks.BASE + "continuation-events.json"
    if change == "missing":
        contents.pop(locator)
    elif change == "extra":
        contents["other.json"] = b"{}"
    else:
        contents[locator] += b" "
    with pytest.raises(ValueError, match="source"):
        clocks.audit(contents)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r["trials"].pop(), "call count"),
        (lambda r: r["trials"][0]["before_call"].pop("finished_monotonic_ns"), "partial"),
        (lambda r: r["trials"][0]["before_call"].update(started_monotonic_ns=True), "integers"),
        (lambda r: r["trials"][0]["before_call"].update(started_utc="2026-09-11T12:00:00"), "UTC"),
    ],
)
def test_clock_audit_does_not_silently_omit_unusable_timing(mutate, message, monkeypatch):
    contents = _contents()
    name = "continuation-events.json"
    value = json.loads(contents[clocks.BASE + name])
    mutate(value)
    contents[clocks.BASE + name] = json.dumps(value).encode()
    # Synthetic mutations bypass only the pinned identity, not arithmetic checks.
    monkeypatch.setitem(
        clocks.SOURCES,
        name,
        (
            hashlib.sha256(contents[clocks.BASE + name]).hexdigest(),
            228,
        ),
    )
    with pytest.raises(ValueError, match=message):
        clocks.audit(contents)


def test_negative_monotonic_interval_is_reported_not_repaired(monkeypatch):
    contents = _contents()
    name = "continuation-events.json"
    value = json.loads(contents[clocks.BASE + name])
    call = value["trials"][0]["before_call"]
    call["finished_monotonic_ns"] = call["started_monotonic_ns"] - 1
    contents[clocks.BASE + name] = json.dumps(value).encode()
    monkeypatch.setitem(
        clocks.SOURCES,
        name,
        (
            hashlib.sha256(contents[clocks.BASE + name]).hexdigest(),
            228,
        ),
    )
    report = clocks.audit(contents)
    assert report["totals"]["negative_monotonic_intervals"] == 1


def test_clock_audit_pointer_escaping():
    assert list(clocks._calls({"a/b~c": {"request": {}, "response": {}}}))[0][0] == "/a~1b~0c"


def test_clock_audit_script_replays_report():
    result = subprocess.run(
        [sys.executable, str(clocks.ROOT / "scripts/audit_capture_clocks.py")],
        cwd=clocks.ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == clocks.audit(_contents())
