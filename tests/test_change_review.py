import copy
import hashlib
import json
from pathlib import Path

import pytest

from agentmandate import compare, loads
from agentmandate._change_review import evaluate, render
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-10-10"


def encoded(value):
    return json.dumps(value, indent=2, sort_keys=True).encode()


def manifests():
    before = {
        "agent": "synthetic-release",
        "limits": {"depth": 4, "total": {"amount": "5", "currency": "GBP"}},
        "tools": [
            {"name": "seed", "effect": "read", "produces": "item"},
            {
                "name": "pay",
                "effect": "irreversible",
                "requires": ["item"],
                "scope_key": "item",
                "value_arg": "amount",
                "requires_approval": True,
                "ceiling": {"amount": "5", "currency": "GBP"},
            },
        ],
    }
    after = copy.deepcopy(before)
    after["tools"][0]["unbounded"] = True
    return encoded(before), encoded(after)


def record(before=None, after=None):
    lhs, rhs = manifests()
    lhs = lhs if before is None else before
    rhs = rhs if after is None else after
    baseline = evaluate(lhs, rhs, as_of=AS_OF)
    source = b"Synthetic decision only; no real deployment approval.\n"
    raw = {
        "schema": "agentmandate.change-review/v1",
        **baseline["inputs"],
        "scope": "all_widening_changes_in_pinned_comparison",
        "owner": "synthetic-owner",
        "reviewer": "synthetic-reviewer",
        "reason": "Accept this bounded authority expansion for the synthetic example.",
        "decision": "accept",
        "reviewed_at": AS_OF,
        "expires": "2026-11-08",
        "evidence": [
            {
                "locator": "review-note",
                "sha256": hashlib.sha256(source).hexdigest(),
                "purpose": "decision",
            }
        ],
        "target_policy": {
            "status": "not_applicable",
            "reason": "No deployed policy in this example.",
        },
    }
    return raw, {"review-note": source}


def run(raw=None, sources=None, **kwargs):
    before, after = manifests()
    if raw is None:
        raw, default_sources = record()
        sources = default_sources if sources is None else sources
    return evaluate(
        before,
        after,
        as_of=kwargs.pop("as_of", AS_OF),
        decision=encoded(raw),
        sources=sources,
        **kwargs,
    )


def rules(report):
    return {row["rule"] for row in report["findings"]}


def test_acceptance_satisfies_only_review_gate_and_retains_full_breach_and_diff():
    before, after = manifests()
    report = run()
    baseline = compare(loads(before.decode()), loads(after.decode())).as_dict()
    assert report["comparison"] == baseline
    assert report["gate_satisfied"] and report["review"]["eligible"]
    assert report["status"] == "eligible_recorded_acceptance"
    assert baseline["direction"] == "widening" and baseline["after"]["breaches"]
    assert not baseline["before"]["breaches"]
    assert baseline["after"]["truncated"]
    assert "not reviewer authentication or deployment approval" in report["scope"]
    assert report["review"]["evidence_checks"][0]["matches"]
    assert "enforcement not verified" in report["review"]["attestation"]
    raw, _ = record()
    assert report["review"]["source_sha256"] == hashlib.sha256(encoded(raw)).hexdigest()
    assert raw["decision"] == "accept" and "eligible" not in raw


def test_widening_without_record_is_finding_and_exposes_exact_review_materials():
    before, after = manifests()
    report = evaluate(before, after, as_of=AS_OF)
    assert not report["gate_satisfied"] and report["review"] is None
    assert report["status"] == "recorded_acceptance_unresolved"
    assert rules(report) == {"review.decision-missing"}
    assert report["inputs"]["before_sha256"] == hashlib.sha256(before).hexdigest()
    assert report["inputs"]["after_sha256"] == hashlib.sha256(after).hexdigest()
    canonical = json.dumps(report["comparison"], sort_keys=True, separators=(",", ":")).encode()
    assert report["inputs"]["comparison_sha256"] == hashlib.sha256(canonical).hexdigest()


@pytest.mark.parametrize("direction", ["neutral", "narrowing"])
def test_nonwidening_requires_no_record_but_does_not_assert_complete_analysis(direction):
    before, after = manifests()
    lhs, rhs = (before, before) if direction == "neutral" else (after, before)
    report = evaluate(lhs, rhs, as_of=AS_OF)
    assert report["comparison"]["direction"] == direction
    assert report["status"] == "review_not_required_within_bound"
    assert report["gate_satisfied"] and report["review"] is None


def test_explicit_record_on_nonwidening_is_still_checked():
    before, _ = manifests()
    raw, sources = record(before, before)
    report = evaluate(before, before, as_of=AS_OF, decision=encoded(raw), sources=sources)
    assert report["gate_satisfied"]
    raw["decision"] = "reject"
    report = evaluate(before, before, as_of=AS_OF, decision=encoded(raw), sources=sources)
    assert not report["gate_satisfied"] and "review.not-accepted" in rules(report)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent", "another-agent"),
        ("depth", 3),
        ("before_sha256", "a" * 64),
        ("after_sha256", "b" * 64),
        ("comparison_sha256", "c" * 64),
    ],
)
def test_record_cannot_move_between_agents_inputs_depths_or_comparisons(field, value):
    raw, sources = record()
    raw[field] = value
    report = run(raw, sources)
    assert not report["gate_satisfied"] and not report["review"]["eligible"]
    assert rules(report) == {"review.comparison-mismatch"}
    assert field in report["findings"][0]["detail"]


def test_one_space_manifest_change_invalidates_raw_join_even_when_diff_is_identical():
    before, after = manifests()
    raw, sources = record()
    report = evaluate(before, after + b" ", as_of=AS_OF, decision=encoded(raw), sources=sources)
    assert report["inputs"]["comparison_sha256"] == raw["comparison_sha256"]
    assert not report["gate_satisfied"]
    assert rules(report) == {"review.comparison-mismatch"}


@pytest.mark.parametrize(
    ("as_of", "rule"),
    [
        ("2026-10-09", "review.not-yet-effective"),
        ("2026-11-09", "review.expired"),
    ],
)
def test_evaluation_outside_inclusive_dates_refuses_eligibility(as_of, rule):
    report = run(as_of=as_of)
    assert rules(report) == {rule} and not report["review"]["eligible"]


@pytest.mark.parametrize("as_of", ["2026-10-10", "2026-11-08"])
def test_review_and_expiry_dates_are_inclusive(as_of):
    assert run(as_of=as_of)["gate_satisfied"]


@pytest.mark.parametrize("decision", ["reject", "defer"])
def test_only_accept_decision_can_satisfy_gate(decision):
    raw, sources = record()
    raw["decision"] = decision
    report = run(raw, sources)
    assert not report["gate_satisfied"] and rules(report) == {"review.not-accepted"}


def test_bad_evidence_expiry_and_unresolved_policy_are_distinct_findings():
    raw, sources = record()
    raw["target_policy"]["status"] = "unresolved"
    sources["review-note"] += b" "
    report = run(raw, sources, as_of="2026-11-09")
    assert rules(report) == {
        "review.evidence-mismatch",
        "review.expired",
        "review.target-policy-unresolved",
    }
    assert not report["gate_satisfied"]
    assert not report["review"]["evidence_checks"][0]["matches"]
    assert report["comparison"]["after"]["breaches"]


def test_recorded_target_policy_checks_bytes_without_claiming_enforcement():
    raw, sources = record()
    raw["target_policy"]["status"] = "evidence_recorded"
    sources["policy"] = b"Caller-attested policy mapping, not live enforcement proof."
    raw["evidence"].append(
        {
            "locator": "policy",
            "sha256": hashlib.sha256(sources["policy"]).hexdigest(),
            "purpose": "target_policy",
        }
    )
    report = run(raw, sources)
    assert report["gate_satisfied"] and len(report["review"]["evidence_checks"]) == 2
    assert report["review"]["target_policy"]["status"] == "evidence_recorded"
    assert "enforcement not verified" in render(report)
    sources["policy"] += b" "
    assert rules(run(raw, sources)) == {"review.evidence-mismatch"}


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema",), "other/v1"),
        (("scope",), "one-change-only"),
        (("owner",), ""),
        (("reviewer",), None),
        (("reason",), "\n"),
        (("agent",), 4),
        (("before_sha256",), "A" * 64),
        (("after_sha256",), None),
        (("comparison_sha256",), "a" * 63),
        (("depth",), True),
        (("depth",), 0),
        (("decision",), "approve"),
        (("reviewed_at",), "20261010"),
        (("reviewed_at",), None),
        (("expires",), "2026-10-09"),
        (("target_policy",), []),
        (("target_policy", "status"), "enforced"),
        (("target_policy", "reason"), ""),
        (("evidence",), []),
        (("evidence",), {}),
        (("evidence", 0, "purpose"), "link"),
        (("evidence", 0, "locator"), "\x00"),
        (("evidence", 0, "sha256"), "bad"),
        (("evidence", 0, "locator"), "unmappable=locator"),
    ],
)
def test_strict_decision_shape_types_and_claims_are_refused(path, value):
    raw, sources = record()
    target = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        run(raw, sources)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "duplicate-locator", "no-decision-evidence", "no-policy-evidence"],
)
def test_decision_requires_complete_closed_records_and_purposeful_evidence(mutation):
    raw, sources = record()
    if mutation == "missing":
        del raw["owner"]
    elif mutation == "extra":
        raw["approved"] = True
    elif mutation == "duplicate-locator":
        raw["evidence"].append(copy.deepcopy(raw["evidence"][0]))
    elif mutation == "no-decision-evidence":
        raw["evidence"][0]["purpose"] = "target_policy"
    else:
        raw["target_policy"]["status"] = "evidence_recorded"
    with pytest.raises(ValueError):
        run(raw, sources)


@pytest.mark.parametrize("sources", [{}, {"unknown": b"anything"}])
def test_missing_or_undeclared_evidence_mapping_is_usage_error(sources):
    raw, _ = record()
    with pytest.raises(ValueError, match="exactly every"):
        run(raw, sources)


@pytest.mark.parametrize("as_of", [None, "20261010", "2026-02-30", "2026-10-10T00:00:00Z"])
def test_explicit_evaluation_date_is_strict(as_of):
    before, after = manifests()
    with pytest.raises(ValueError):
        evaluate(before, after, as_of=as_of)


@pytest.mark.parametrize("content", [b"[]", b'{"schema":1,"schema":2}', b"bad", b"\xff"])
def test_bad_decision_bytes_are_refused(content):
    before, after = manifests()
    with pytest.raises(ValueError):
        evaluate(before, after, as_of=AS_OF, decision=content)


def test_source_bytes_without_record_are_refused():
    before, after = manifests()
    with pytest.raises(ValueError, match="require a decision"):
        evaluate(before, after, as_of=AS_OF, sources={"note": b"something"})


def inputs(tmp_path):
    before, after = manifests()
    raw, sources = record()
    paths = {}
    for name, data in {"before": before, "after": after, "record": encoded(raw), **sources}.items():
        paths[name] = tmp_path / name
        paths[name].write_bytes(data)
    args = [
        "review",
        str(paths["before"]),
        str(paths["after"]),
        "--as-of",
        AS_OF,
        "--decision",
        str(paths["record"]),
        "--source",
        f"review-note={paths['review-note']}",
    ]
    return paths, args


def test_cli_accepts_scoped_review_but_diff_and_reach_still_fail(tmp_path, capsys):
    paths, args = inputs(tmp_path)
    assert main([*args, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "eligible_recorded_acceptance"
    assert main(["diff", str(paths["before"]), str(paths["after"]), "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == report["comparison"]
    assert main(["reach", str(paths["after"]), "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == report["comparison"]["after"]
    assert main(args) == 0
    text = capsys.readouterr().out
    assert "eligible_recorded_acceptance" in text and "BREACH cumulative_value" in text
    assert "not reviewer authentication or deployment approval" in text
    assert "Authority findings remain unchanged" in text


def test_cli_tamper_expiry_and_missing_decision_write_complete_finding(tmp_path, capsys):
    paths, args = inputs(tmp_path)
    paths["review-note"].write_bytes(b"different")
    args[args.index(AS_OF)] = "2026-11-09"
    assert main([*args, "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert rules(report) == {"review.evidence-mismatch", "review.expired"}
    assert main(args) == 1
    assert "FINDING review.expired" in capsys.readouterr().out
    assert main(args[:5]) == 1
    assert "review.decision-missing" in capsys.readouterr().out


def test_cli_clean_comparison_does_not_require_a_decision(tmp_path, capsys):
    paths, _ = inputs(tmp_path)
    assert (
        main(["review", str(paths["before"]), str(paths["before"]), "--as-of", AS_OF, "--json"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "review_not_required_within_bound"


@pytest.mark.parametrize(
    "bad",
    [
        "missing-before",
        "missing-after",
        "missing-record",
        "missing-source",
        "bad-record",
        "utf8-record",
        "bad-before",
        "bad-after",
        "bad-date",
        "duplicate-map",
        "bad-map",
        "empty-locator",
        "empty-path",
        "unknown-map",
        "no-map",
    ],
)
def test_cli_usage_io_and_input_failures_emit_no_partial_output(tmp_path, capsys, bad):
    paths, args = inputs(tmp_path)
    if bad.startswith("missing-"):
        name = bad.removeprefix("missing-")
        paths["review-note" if name == "source" else name].unlink()
    elif bad == "bad-record":
        paths["record"].write_bytes(b"not json")
    elif bad == "utf8-record":
        paths["record"].write_bytes(b"\xff")
    elif bad in {"bad-before", "bad-after"}:
        paths[bad.removeprefix("bad-")].write_bytes(b"[]")
    elif bad == "bad-date":
        args[args.index(AS_OF)] = "bad"
    elif bad == "duplicate-map":
        args.extend(args[-2:])
    elif bad in {"bad-map", "empty-locator", "empty-path"}:
        args[-1] = {"bad-map": "bad", "empty-locator": "=file", "empty-path": "note="}[bad]
    elif bad == "unknown-map":
        args[-1] = f"unknown={paths['review-note']}"
    else:
        args = args[:-2]
    assert main([*args, "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("error:")


def test_cli_source_file_can_contain_equals_in_its_path(tmp_path, capsys):
    paths, args = inputs(tmp_path)
    renamed = tmp_path / "notes=review.txt"
    paths["review-note"].rename(renamed)
    args[-1] = f"review-note={renamed}"
    assert main([*args, "--json"]) == 0
    capsys.readouterr()


def test_changed_depth_and_cross_agent_comparison_cannot_reuse_record(tmp_path, capsys):
    paths, args = inputs(tmp_path)
    assert main([*args, "--depth", "3", "--json"]) == 1
    assert "review.comparison-mismatch" in rules(json.loads(capsys.readouterr().out))
    raw = json.loads(paths["after"].read_text())
    raw["agent"] = "other"
    paths["after"].write_bytes(encoded(raw))
    assert main([*args, "--json"]) == 2
    assert capsys.readouterr().out == ""


def test_historical_acceptance_is_not_a_release_decision(tmp_path, capsys):
    _, args = inputs(tmp_path)
    args[args.index("--decision") + 1] = str(
        ROOT / "docs/continuity-reviews/agentcore-continuation-2026-10-09.json"
    )
    assert main([*args, "--json"]) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("name", ["accepted", "expired", "missing", "neutral", "deferred"])
def test_v1_baselines_replay_exact_output_and_exit(name, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    fixture = json.loads((ROOT / f"tests/fixtures/change-review-{name}-v1.json").read_text())
    assert main(fixture["argv"]) == fixture["exit"]
    captured = capsys.readouterr()
    assert json.loads(captured.out) == fixture["result"] and captured.err == ""


@pytest.mark.parametrize(
    "flags", [[], ["--as-of", AS_OF, "--depth", "0"], ["--as-of", AS_OF, "--ir", "snapshot.json"]]
)
def test_cli_missing_date_invalid_depth_and_unimplemented_composition_fail_closed(flags, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["review", "before", "after", *flags, "--json"])
    assert exc.value.code == 2 and capsys.readouterr().out == ""


def test_cli_sources_without_decision_are_refused(tmp_path, capsys):
    paths, args = inputs(tmp_path)
    assert main([*args[:5], "--source", f"review-note={paths['review-note']}", "--json"]) == 2
    assert capsys.readouterr().out == ""


def test_review_never_mutates_input_record_or_source_files(tmp_path, capsys):
    paths, args = inputs(tmp_path)
    before = {path: path.read_bytes() for path in paths.values()}
    assert main([*args, "--json"]) == 0
    capsys.readouterr()
    assert {path: path.read_bytes() for path in paths.values()} == before
