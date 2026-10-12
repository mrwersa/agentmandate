"""Exact request comparisons preserve independent release and capture blockers."""

import copy
import hashlib
import json
import os
import shutil
import subprocess
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from pathlib import Path

import pytest

from agentmandate import analyse, loads
from agentmandate._deployment_reconcile import reconcile
from agentmandate._rego_diff import _number, _request_json, compare, render
from agentmandate._rego_export import export
from agentmandate.cli import main
from agentmandate.diff import compare as authority_compare

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/rego-diff"
AS_OF = "2026-10-12"


def encode(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def read(root, path):
    return json.loads((root / path).read_bytes())


def spec(side):
    return (EXAMPLE / (side + ".json")).read_bytes()


def run(root=ROOT, *, baseline="baseline", candidate="candidate", as_of=AS_OF):
    return compare(
        spec(baseline), spec(candidate), baseline_root=root, candidate_root=root, as_of=as_of
    )


def codes(report):
    return {row["code"] for row in report["findings"]}


def rows(telemetry):
    return telemetry["resourceSpans"][0]["scopeSpans"][0]["spans"]


@pytest.fixture
def artifacts(tmp_path):
    for name in ("rego-export", "deployment-reconcile", "rego-diff"):
        shutil.copytree(ROOT / "examples" / name, tmp_path / "examples" / name)
    return tmp_path


def material(root, name, side="candidate"):
    capture = json.loads(spec(side))
    return root / capture[name]


def edit(root, name, mutate, side="candidate"):
    path = material(root, name, side)
    value = json.loads(path.read_bytes())
    mutate(value)
    path.write_bytes(encode(value))


def repin(root, side="candidate"):
    path = material(root, "mapping", side)
    mapping = json.loads(path.read_bytes())
    mapping["pins"] = {
        name: hashlib.sha256(material(root, name, side).read_bytes()).hexdigest()
        for name in ("manifest", "configuration", "decisions", "telemetry")
    }
    path.write_bytes(encode(mapping))


def refresh(root, side="candidate"):
    """Update declared correlation after a test changes one scoped input."""
    capture = json.loads(spec(side))
    content = {
        name: (root / capture[name]).read_bytes()
        for name in capture
        if name != "rego_capture_version"
    }
    config, mapping = json.loads(content["configuration"]), json.loads(content["mapping"])
    records, telemetry = json.loads(content["decisions"]), json.loads(content["telemetry"])
    digests = {
        name + "_sha256": hashlib.sha256(content[name]).hexdigest()
        for name in ("manifest", "configuration")
    }
    for index, record in enumerate(records):
        correlation = record["input"][mapping["input_key"]]
        correlation.update(digests, gateway=config["gateway"]["id"])
        record["bundles"] = {mapping["bundle"]: {"revision": config["policy"]["revision"]}}
        attributes = {a["key"]: a for a in rows(telemetry)[index]["attributes"]}
        values = {
            **correlation,
            "decision_id": record["decision_id"],
            "policy_revision": config["policy"]["revision"],
            **{f: record["input"][f] for f in ("principal", "action", "resource")},
        }
        for field, value in values.items():
            if field in mapping["attributes"]:
                attributes[mapping["attributes"][field]]["value"] = {
                    "intValue" if type(value) is int else "stringValue": value,
                }
    material(root, "decisions", side).write_bytes(encode(records))
    material(root, "telemetry", side).write_bytes(encode(telemetry))
    repin(root, side)


def rebuild_export(root, side="candidate"):
    config = json.loads(material(root, "configuration", side).read_bytes())
    manifest = material(root, "manifest", side).read_bytes()
    mapping = (root / config["export"]["mapping"]).read_bytes()
    receipt = export(manifest, mapping, allow_partial=True)
    (root / config["export"]["receipt"]).write_bytes(encode(receipt))
    (root / config["policy"]["files"]["policy.rego"]).write_text(receipt["policy"])
    (root / config["policy"]["files"]["schema.json"]).write_text(
        json.dumps(receipt["input_schema"], indent=2, sort_keys=True) + "\n"
    )
    refresh(root, side)


def test_widening_is_concrete_scoped_and_keeps_both_unmodified_reconciliations():
    report = run()
    assert report["summary"] == {"requests": 3, "compared": 3, "widened": 1}
    assert codes(report) == {
        "rego.decision-widened",
        "rego.authority-widened",
        "rego.authority-breach",
    }
    widened = next(r for r in report["comparisons"] if r["baseline_result"] is False)
    assert widened["candidate_result"] is True
    assert widened["relation"] == "widens_within_captured_scope"
    assert widened["tools"] == {"baseline": ["publish_release"], "candidate": ["publish_release"]}
    for side in ("baseline", "candidate"):
        capture = json.loads(spec(side))
        content = [
            material(ROOT, name, side).read_bytes()
            for name in ("manifest", "configuration", "decisions", "telemetry", "mapping")
        ]
        assert report[side] == reconcile(*content, root=ROOT, as_of=AS_OF)
        assert report["inputs"][side]["capture_sha256"] == hashlib.sha256(spec(side)).hexdigest()
        assert (
            report[side]["deployment"]["authority"]
            == analyse(loads((ROOT / capture["manifest"]).read_text())).as_dict()
        )
    assert (
        report["authority_diff"]
        == authority_compare(
            loads(material(ROOT, "manifest", "baseline").read_text()),
            loads(material(ROOT, "manifest").read_text()),
        ).as_dict()
    )
    assert all(
        report[k] == "not_assessed" for k in ("ordering", "accounting", "runtime_continuity")
    )
    assert report["native_validation"] == "not_run"
    text = render(report)
    assert "publish_release" in text and "baseline=Deny candidate=Allow" in text
    assert "AUTHORITY DIFF" in text and "not policy equivalence" in text


@pytest.mark.parametrize(
    "before,after,relation",
    [
        ("baseline", "baseline", "stable_deny_within_captured_scope"),
        ("candidate", "baseline", "narrows_within_captured_scope"),
    ],
)
def test_unchanged_and_narrowing_captures_are_clean(before, after, relation):
    report = run(baseline=before, candidate=after)
    assert not report["findings"]
    assert report["status"] == "no_widening_within_captured_scope"
    assert relation in {r["relation"] for r in report["comparisons"]}


@pytest.mark.parametrize(
    "as_of,current", [("2026-10-11", False), ("2026-11-08", True), ("2026-11-09", False)]
)
def test_expiry_or_not_yet_observed_nulls_comparison_values(as_of, current):
    report = run(as_of=as_of)
    assert report["boundary_comparable"] is current
    assert report["summary"]["compared"] == (3 if current else 0)
    if not current:
        assert "rego.decision-widened" not in codes(report)
        assert all(
            r["baseline_result"] is r["candidate_result"] is None for r in report["comparisons"]
        )
        assert report["candidate"]["deployment"]["authority"]["breaches"]


@pytest.mark.parametrize("pin", ["manifest", "configuration", "decisions", "telemetry"])
def test_tampered_source_pin_cannot_supply_a_positive_comparison(artifacts, pin):
    edit(artifacts, "mapping", lambda m: m["pins"].update({pin: "0" * 64}))
    report = run(artifacts)
    assert "rego.capture-unresolved" in codes(report)
    assert report["summary"]["compared"] == 0
    assert "rego.authority-breach" in codes(report)


@pytest.mark.parametrize("source", ["decisions", "telemetry"])
@pytest.mark.parametrize("coverage", ["partial", "unknown"])
def test_incomplete_coverage_never_makes_an_absence_clean(artifacts, source, coverage):
    edit(artifacts, "mapping", lambda m: m["coverage"].update({source: coverage}))
    report = run(artifacts)
    assert not report["boundary_comparable"]
    assert report["summary"]["compared"] == 0
    assert "reconciliation.coverage-incomplete" in codes(report["candidate"])


def test_contradictory_recorded_decision_is_not_a_widening_witness(artifacts):
    edit(artifacts, "decisions", lambda r: r[0].update(result=False))
    repin(artifacts)
    report = run(artifacts)
    assert "reconciliation.decision-contradiction" in codes(report["candidate"])
    assert "rego.decision-widened" not in codes(report)
    assert report["summary"]["compared"] == 0


@pytest.mark.parametrize("field", ["masked", "erased"])
def test_unrelated_payload_masking_cannot_establish_exact_request_equality(artifacts, field):
    edit(artifacts, "decisions", lambda r: r[0].update({field: ["/input/payload"]}))
    repin(artifacts)
    report = run(artifacts)
    assert not report["candidate"]["findings"]
    assert report["summary"]["compared"] == 2
    unresolved = next(r for r in report["comparisons"] if r["relation"] == "unresolved")
    assert unresolved["baseline_result"] is unresolved["candidate_result"] is None


def test_masking_outside_policy_input_does_not_block_exact_request_comparison(artifacts):
    edit(artifacts, "decisions", lambda r: r[0].update(masked=["/timestamp"]))
    repin(artifacts)
    assert run(artifacts)["summary"]["compared"] == 3


def test_distinct_inputs_are_unmatched_even_when_the_generated_policy_ignores_the_difference(
    artifacts,
):
    edit(
        artifacts,
        "decisions",
        lambda r: r[1]["input"].update(payload={"business_case": "different"}),
    )
    repin(artifacts)
    report = run(artifacts)
    assert not report["candidate"]["findings"]
    assert report["summary"] == {"requests": 4, "compared": 2, "widened": 0}
    assert "rego.request-unmatched-or-ambiguous" in codes(report)
    assert all(
        r["baseline_result"] is r["candidate_result"] is None
        for r in report["comparisons"]
        if r["relation"] == "unresolved"
    )


def test_repeated_exact_requests_with_distinct_attempt_ids_are_not_silently_paired(artifacts):
    records = json.loads(material(artifacts, "decisions").read_bytes())
    duplicate = copy.deepcopy(records[0])
    duplicate["decision_id"] = "synthetic-extra-decision"
    duplicate["input"]["agentmandate"]["invocation_id"] = "synthetic-extra-invocation"
    records.append(duplicate)
    material(artifacts, "decisions").write_bytes(encode(records))
    telemetry = json.loads(material(artifacts, "telemetry").read_bytes())
    rows(telemetry).append(copy.deepcopy(rows(telemetry)[0]))
    material(artifacts, "telemetry").write_bytes(encode(telemetry))
    refresh(artifacts)
    report = run(artifacts)
    assert not report["candidate"]["findings"]
    assert report["summary"]["compared"] == 2
    assert "rego.request-unmatched-or-ambiguous" in codes(report)


def test_array_order_and_correlation_identifiers_do_not_select_the_pair(artifacts):
    edit(artifacts, "decisions", lambda r: r.reverse())
    edit(artifacts, "telemetry", lambda t: rows(t).reverse())
    repin(artifacts)
    assert run(artifacts)["comparisons"] == run()["comparisons"]


def test_stable_captured_requests_cannot_erase_independent_manifest_findings(artifacts):
    for side in ("baseline", "candidate"):
        edit(artifacts, "decisions", lambda rs: rs.pop(1), side)
        edit(artifacts, "telemetry", lambda t: rows(t).pop(1), side)
        repin(artifacts, side)
    report = run(artifacts)
    assert not report["baseline"]["findings"] and not report["candidate"]["findings"]
    assert report["summary"] == {"requests": 2, "compared": 2, "widened": 0}
    assert codes(report) == {"rego.authority-widened", "rego.authority-breach"}


@pytest.mark.parametrize(
    "field", ["agent", "identity", "environment", "gateway", "bundle", "input_key", "query_path"]
)
def test_changed_comparison_boundary_leaves_same_requests_unresolved(artifacts, field):
    config = json.loads(material(artifacts, "configuration").read_bytes())
    if field in ("agent", "identity", "query_path"):
        mapping = read(artifacts, config["export"]["mapping"])
        if field == "query_path":
            mapping["package"] = "other_package"
            edit(
                artifacts,
                "decisions",
                lambda rs: [r.update(path="other_package/allow") for r in rs],
            )
        else:
            mapping[field] = "different"
            config[field] = "different"
            edit(artifacts, "manifest", lambda m: m.update({field: "different"}))
        export_path = "examples/rego-diff/candidate/export-mapping.json"
        (artifacts / export_path).write_bytes(encode(mapping))
        config["export"]["mapping"] = export_path
    elif field == "environment":
        config[field] = "different"
    elif field == "gateway":
        config["gateway"]["id"] = "different"
    elif field == "bundle":
        edit(artifacts, "mapping", lambda m: m.update(bundle="other_bundle"))
    else:
        edit(artifacts, "mapping", lambda m: m.update(input_key="correlation"))
        edit(
            artifacts,
            "decisions",
            lambda rs: [r["input"].update(correlation=r["input"].pop("agentmandate")) for r in rs],
        )
    material(artifacts, "configuration").write_bytes(encode(config))
    rebuild_export(artifacts)
    report = run(artifacts)
    assert not report["candidate"]["findings"]
    assert "rego.boundary-mismatch" in codes(report)
    assert any(r["subject"] == field for r in report["findings"])
    assert report["summary"]["compared"] == 0
    if field == "agent":
        assert report["authority_diff"] is None
        assert "BASELINE AUTHORITY" in render(report)
        assert "CANDIDATE AUTHORITY" in render(report)


def test_same_revision_label_cannot_name_different_policy_bytes(artifacts):
    config = json.loads(material(artifacts, "configuration").read_bytes())
    config["policy"]["revision"] = "release-policy-r1"
    for route in config["gateway"]["routes"]:
        route["policy_revision"] = "release-policy-r1"
    material(artifacts, "configuration").write_bytes(encode(config))
    refresh(artifacts)
    report = run(artifacts)
    assert not report["candidate"]["findings"]
    assert "rego.revision-conflict" in codes(report)
    assert report["summary"]["compared"] == 0


def test_missing_policy_bytes_are_unresolved_not_a_proven_revision_conflict(artifacts):
    edit(artifacts, "configuration", lambda c: c["policy"]["files"].pop("policy.rego"))
    refresh(artifacts)
    report = run(artifacts)
    assert "rego.capture-unresolved" in codes(report)
    assert "rego.revision-conflict" not in codes(report)
    assert report["summary"]["compared"] == 0


def test_unsupported_effect_budgets_and_reachable_breaches_survive_comparison(artifacts):
    edit(artifacts, "manifest", lambda m: m.update(limits={"effects": {"read": 0}, "depth": 3}))
    rebuild_export(artifacts)
    report = run(artifacts)
    assert report["candidate"]["deployment"]["export"]["losses"]
    assert "deployment.control-uncompiled" in codes(report["candidate"])
    assert {"rego.capture-unresolved", "rego.authority-breach"} <= codes(report)
    assert "effect_count" in {b["kind"] for b in report["authority_diff"]["after"]["breaches"]}
    assert report["summary"]["compared"] == 0
    assert "CANDIDATE FINDING deployment.control-uncompiled" in render(report)


def test_untyped_requests_are_retained_as_findings_without_keyerror(artifacts):
    edit(artifacts, "decisions", lambda rs: rs[0].update(input="malformed"))
    repin(artifacts)
    report = run(artifacts)
    assert "rego.request-unresolved" in codes(report)
    assert report["summary"]["compared"] == 0


def test_reserved_correlation_field_cannot_remove_policy_semantics(artifacts):
    edit(artifacts, "mapping", lambda m: m.update(input_key="context"))
    with pytest.raises(ValueError, match="must not replace"):
        run(artifacts)


def test_mapping_cannot_change_between_reconciliation_and_comparison(monkeypatch):
    from agentmandate import _rego_diff

    original = _rego_diff._read

    def changed(root, locator):
        return b"{}" if locator == "examples/rego-export/mapping.json" else original(root, locator)

    monkeypatch.setattr(_rego_diff, "_read", changed)
    with pytest.raises(ValueError, match="changed during comparison"):
        run()


def argv(baseline="baseline", candidate="candidate", root=ROOT):
    return [
        "rego",
        "diff",
        "--baseline",
        str(EXAMPLE / (baseline + ".json")),
        "--candidate",
        str(EXAMPLE / (candidate + ".json")),
        "--baseline-root",
        str(root),
        "--candidate-root",
        str(root),
        "--as-of",
        AS_OF,
    ]


@pytest.mark.parametrize(
    "left,right,equal",
    [
        ("1", "1.0", True),
        ("1.00", "1e0", True),
        ("1000", "1.000e3", True),
        ("-1.2300", "-123e-2", True),
        ("0", "-0.000e100", True),
        ("0.1", "0.1000000000000000055511151231257827", False),
        ("9007199254740992", "9007199254740993", False),
        ("1e-999", "2e-999", False),
        ("1e999", "10e998", True),
        ("1e1000000", "10e999999", True),
        ("true", "1", False),
        ('"1"', "1", False),
        ('{"a":[1,0.1],"b":null}', '{"b":null,"a":[1.0,1e-1]}', True),
        ("[1,2]", "[2,1]", False),
    ],
)
def test_exact_request_identity_controls_full_comparison_and_cli(
    artifacts, left, right, equal, capsys
):
    other = artifacts / "other"
    shutil.copytree(artifacts / "examples", other / "examples")
    for root, literal in ((artifacts, left), (other, right)):
        path = material(root, "decisions", "baseline")
        records = json.loads(path.read_bytes())
        for record in records:
            record["input"]["context"]["note"] = "EXACT_NUMBER_PLACEHOLDER"
        path.write_bytes(
            encode(records).replace(b'"EXACT_NUMBER_PLACEHOLDER"', literal.encode())
        )
        repin(root, "baseline")
    with localcontext() as context:
        context.prec = 2
        report = compare(
            spec("baseline"), spec("baseline"),
            baseline_root=artifacts, candidate_root=other, as_of=AS_OF,
        )
    assert report["boundary_comparable"]
    assert not report["baseline"]["findings"] and not report["candidate"]["findings"]
    assert report["summary"] == {
        "requests": 3 if equal else 6, "compared": 3 if equal else 0, "widened": 0,
    }
    assert codes(report) == (set() if equal else {"rego.request-unmatched-or-ambiguous"})
    command = argv("baseline", "baseline", artifacts) + ["--json"]
    command[command.index("--candidate-root") + 1] = str(other)
    assert main(command) == (0 if equal else 1)
    assert json.loads(capsys.readouterr().out) == report


def test_number_normalization_matches_exact_rational_reference_without_context_rounding():
    by_value = {}
    by_encoding = {}
    with localcontext() as context:
        context.prec = 1
        for coefficient in range(-20, 21):
            for exponent in range(-4, 5):
                literal = f"{coefficient}e{exponent}"
                value = Fraction(literal)
                encoded = _request_json(Decimal(literal))
                assert Fraction(encoded) == value
                assert by_value.setdefault(value, encoded) == encoded
                assert by_encoding.setdefault(encoded, value) == value
                assert _request_json(Decimal(f"{coefficient}0e{exponent - 1}")) == encoded
    assert len(_request_json(Decimal("1e1000000"))) < 20


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e9999999999999999999999"])
def test_invalid_request_numbers_are_usage_errors(artifacts, literal, capsys):
    path = material(artifacts, "decisions", "baseline")
    records = json.loads(path.read_bytes())
    records[0]["input"]["context"]["note"] = "INVALID_NUMBER_PLACEHOLDER"
    path.write_bytes(encode(records).replace(b'"INVALID_NUMBER_PLACEHOLDER"', literal.encode()))
    repin(artifacts, "baseline")
    assert main(argv("baseline", "baseline", artifacts) + ["--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and output.err.startswith("error: ")
    assert "Traceback" not in output.err


def test_decimal_range_error_is_a_value_error():
    with pytest.raises(ValueError, match="supported decimal range"):
        _number("1e9999999999999999999999")
    with localcontext() as context:
        context.traps[InvalidOperation] = False
        with pytest.raises(ValueError, match="supported decimal range"):
            _number("1e9999999999999999999999")


@pytest.mark.parametrize(
    "left,right,matched",
    [("1", "1.0", True), ("0.1", "0.1000000000000000055511151231257827", False)],
)
def test_exact_numeric_matching_never_hides_independent_authority_widening(
    artifacts, left, right, matched
):
    for side, literal in (("baseline", left), ("candidate", right)):
        path = material(artifacts, "decisions", side)
        records = json.loads(path.read_bytes())
        for record in records:
            record["input"]["context"]["note"] = "NUMERIC_NOTE_PLACEHOLDER"
        path.write_bytes(encode(records).replace(b'"NUMERIC_NOTE_PLACEHOLDER"', literal.encode()))
        repin(artifacts, side)
    report = run(artifacts)
    assert {"rego.authority-widened", "rego.authority-breach"} <= codes(report)
    assert report["summary"]["widened"] == (1 if matched else 0)
    assert ("rego.decision-widened" in codes(report)) is matched
    assert ("rego.request-unmatched-or-ambiguous" in codes(report)) is not matched


@pytest.mark.parametrize(
    "case",
    json.loads((ROOT / "tests/fixtures/rego-effective-diff-v1.json").read_text()),
    ids=lambda case: case["name"],
)
def test_initial_replay_baselines_pin_complete_reports_and_cli_exits(case, capsys):
    assert (
        run(baseline=case["baseline"], candidate=case["candidate"], as_of=case["as_of"])
        == case["result"]
    )
    command = argv(case["baseline"], case["candidate"])
    command[-1] = case["as_of"]
    assert main(command + ["--json"]) == case["exit"]
    assert json.loads(capsys.readouterr().out) == case["result"]


@pytest.mark.parametrize(
    "before,after,expected",
    [("baseline", "candidate", 1), ("baseline", "baseline", 0), ("candidate", "baseline", 0)],
)
@pytest.mark.parametrize("machine", [False, True])
def test_cli_gate_has_scoped_results_for_widening_unchanged_and_narrowing(
    before, after, expected, machine, capsys
):
    assert main(argv(before, after) + (["--json"] if machine else [])) == expected
    output = capsys.readouterr()
    assert not output.err
    if machine:
        assert json.loads(output.out) == run(baseline=before, candidate=after)
    else:
        assert "REGO DIFF" in output.out and "AUTHORITY DIFF" in output.out


@pytest.mark.parametrize("value", [True, 0, 2, "1"])
def test_unsupported_capture_set_versions_are_usage_errors(value):
    capture = json.loads(spec("baseline"))
    capture["rego_capture_version"] = value
    with pytest.raises(ValueError, match="unsupported rego_capture_version"):
        compare(
            encode(capture), spec("candidate"), baseline_root=ROOT, candidate_root=ROOT, as_of=AS_OF
        )


@pytest.mark.parametrize(
    "fault",
    [
        "extra-field",
        "duplicate-key",
        "nonfinite",
        "overflow",
        "traversal",
        "absolute",
        "missing",
        "utf8",
        "deep",
        "date",
    ],
)
def test_cli_malformed_sources_return_2_without_partial_output(fault, tmp_path, capsys):
    capture = json.loads(spec("baseline"))
    args = argv()
    if fault == "extra-field":
        capture["extra"] = 1
    elif fault in ("traversal", "absolute", "missing"):
        capture["decisions"] = {
            "traversal": "../outside.json",
            "absolute": "/etc/passwd",
            "missing": "absent.json",
        }[fault]
    content = encode(capture)
    if fault == "duplicate-key":
        content = content.replace(
            b'"rego_capture_version": 1', b'"rego_capture_version": 1, "rego_capture_version": 1'
        )
    elif fault in ("nonfinite", "overflow"):
        content = content.replace(
            b'"rego_capture_version": 1',
            b'"rego_capture_version": ' + (b"NaN" if fault == "nonfinite" else b"1e999"),
        )
    elif fault == "utf8":
        content = b"\xff"
    elif fault == "deep":
        content = b"[" * 10000 + b"]" * 10000
    elif fault == "date":
        args[-1] = "tomorrow"
    path = tmp_path / "capture.json"
    path.write_bytes(content)
    args[args.index("--baseline") + 1] = str(path)
    assert main(args + ["--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and output.err.startswith("error: ")
    assert "Traceback" not in output.err


def test_cli_refuses_root_escaping_symlink(artifacts, tmp_path, capsys):
    outside = tmp_path.parent / "outside-decisions.json"
    outside.write_bytes(material(artifacts, "decisions").read_bytes())
    path = material(artifacts, "decisions")
    path.unlink()
    path.symlink_to(outside)
    assert main(argv(root=artifacts) + ["--json"]) == 2
    assert not capsys.readouterr().out


def test_native_opa_reproduces_the_exact_widening_request(tmp_path):
    binary = os.environ.get("AGENTMANDATE_OPA") or shutil.which("opa")
    if not binary:
        if os.environ.get("AGENTMANDATE_REQUIRE_OPA_NATIVE") == "1":
            pytest.fail("native OPA binary is required")
        pytest.skip("native OPA binary not available")
    target = json.loads((ROOT / "examples/rego-export/opa-target.json").read_text())
    assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == target["sha256"]
    for side, expected in [("baseline", [True, False, True]), ("candidate", [True, True, True])]:
        capture = json.loads(spec(side))
        config = read(ROOT, capture["configuration"])
        policy = ROOT / config["policy"]["files"]["policy.rego"]
        subprocess.run([binary, "check", "--strict", str(policy)], check=True, capture_output=True)
        for record, decision in zip(read(ROOT, capture["decisions"]), expected, strict=True):
            request = tmp_path / "input.json"
            request.write_bytes(encode(record["input"]))
            evaluated = subprocess.run(
                [
                    binary,
                    "eval",
                    "--data",
                    str(policy),
                    "--input",
                    str(request),
                    "--format=json",
                    "data.release_gate.allow",
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            assert json.loads(evaluated.stdout)["result"][0]["expressions"][0]["value"] is decision
            assert record["result"] is decision
    assert run()["summary"]["widened"] == 1
