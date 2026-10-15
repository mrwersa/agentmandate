"""Captured request joins, typed telemetry and independent baseline preservation."""

import copy
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agentmandate._deployment_drift import evaluate
from agentmandate._deployment_reconcile import _expected, reconcile, render
from agentmandate._rego_export import export
from agentmandate.cli import main
from agentmandate.manifest import loads
from agentmandate.reach import analyse

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/deployment-reconcile"
MANIFEST = (EXAMPLE / "manifest.json").read_bytes()
CONFIG = (EXAMPLE / "config.json").read_bytes()


def encode(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def data(name):
    return json.loads((EXAMPLE / name).read_bytes())


def spans(value):
    return value["resourceSpans"][0]["scopeSpans"][0]["spans"]


def attr(value, index, field, replacement):
    key = "app.authority." + field
    row = next(a for a in spans(value)[index]["attributes"] if a["key"] == key)
    row["value"] = replacement


def run(
    records=None,
    telemetry=None,
    mapping=None,
    *,
    manifest=MANIFEST,
    config=CONFIG,
    root=ROOT,
    as_of="2026-10-11",
    repin=True,
):
    records = data("decisions.json") if records is None else records
    telemetry = data("telemetry.json") if telemetry is None else telemetry
    mapping = data("mapping.json") if mapping is None else mapping
    inputs = {
        "manifest": manifest,
        "configuration": config,
        "decisions": encode(records),
        "telemetry": encode(telemetry),
    }
    if repin:
        mapping = copy.deepcopy(mapping)
        mapping["pins"] = {
            name: hashlib.sha256(content).hexdigest() for name, content in inputs.items()
        }
    return reconcile(
        manifest,
        config,
        inputs["decisions"],
        inputs["telemetry"],
        encode(mapping),
        root=root,
        as_of=as_of,
    )


def codes(report):
    return {row["code"] for row in report["findings"]}


def test_initial_baseline_has_three_scoped_pairs_and_separate_authority():
    report = reconcile(
        MANIFEST,
        CONFIG,
        (EXAMPLE / "decisions.json").read_bytes(),
        (EXAMPLE / "telemetry.json").read_bytes(),
        (EXAMPLE / "mapping.json").read_bytes(),
        root=ROOT,
        as_of="2026-10-11",
    )
    assert report == json.loads((ROOT / "tests/fixtures/deployment-reconcile-v2.json").read_text())
    assert not report["findings"]
    assert report["summary"]["matched_attempts"] == 3
    assert report["status"] == "consistent_with_captured_join"
    assert report["deployment"] == evaluate(MANIFEST, CONFIG, root=ROOT, as_of="2026-10-11")
    assert all(
        report[field] == "not_assessed"
        for field in ("ordering", "runtime_continuity", "accounting")
    )
    assert report["native_validation"] == "not_run"
    assert "not authenticated live enforcement" in render(report)
    assert "AUTHORITY" in render(report)


def test_reported_denied_effect_is_a_finding_without_changing_authority():
    report = run(telemetry=data("denied-effect-telemetry.json"))
    assert codes(report) == {"reconciliation.denied-effect-observed"}
    assert report["summary"]["matched_attempts"] == 3
    assert report["attempts"][1]["reported_effect_applied"] is True
    assert report["deployment"]["authority"] == run()["deployment"]["authority"]
    assert "causal order not established" in report["findings"][0]["detail"]


@pytest.mark.parametrize("pin", ["manifest", "configuration", "decisions", "telemetry"])
def test_wrong_source_pin_nulls_positive_claims(pin):
    mapping = data("mapping.json")
    mapping["pins"][pin] = "0" * 64
    report = run(mapping=mapping, repin=False)
    assert "reconciliation.source-mismatch" in codes(report)
    assert report["summary"]["matched_attempts"] == 0
    assert all(
        row["observed_result"] is row["expected_export_result"] is None
        for row in report["decisions"]
    )
    assert all(row["reported_effect_applied"] is None for row in report["attempts"])


@pytest.mark.parametrize(
    "as_of,current",
    [("2026-10-10", False), ("2026-10-11", True), ("2026-11-08", True), ("2026-11-09", False)],
)
def test_inclusive_capture_and_config_windows(as_of, current):
    report = run(as_of=as_of)
    assert report["capture_current"] is current
    assert (not report["findings"]) is current
    assert report["summary"]["matched_attempts"] == (3 if current else 0)


@pytest.mark.parametrize("coverage", ["complete", "partial", "unknown"])
@pytest.mark.parametrize("source", ["decisions", "telemetry"])
def test_missing_pairs_depend_on_declared_coverage_and_never_pass_empty(source, coverage):
    mapping = data("mapping.json")
    mapping["coverage"][source] = coverage
    kwargs = {"records": []} if source == "decisions" else {"telemetry": {"resourceSpans": []}}
    report = run(mapping=mapping, **kwargs)
    assert "reconciliation.capture-empty" in codes(report)
    expected = ("decision" if source == "decisions" else "span") + (
        "-missing" if coverage == "complete" else "-unresolved"
    )
    assert "reconciliation." + expected in codes(report)
    if coverage != "complete":
        assert "reconciliation.coverage-incomplete" in codes(report)
        assert not any(code.endswith("-missing") for code in codes(report))


def test_duplicate_decisions_are_ambiguous_even_when_one_has_an_unselected_path():
    records = data("decisions.json")
    records.append({**records[0], "path": "unrelated/allow"})
    report = run(records=records)
    assert "reconciliation.decision-ambiguous" in codes(report)
    assert "reconciliation.decision-unresolved" in codes(report)
    assert "reconciliation.decision-missing" not in codes(report)
    assert report["decisions"][0]["observed_result"] is None
    assert report["summary"]["ignored_decisions"] == 1


@pytest.mark.parametrize("change", ["same-decision", "same-invocation"])
def test_multiple_attempts_never_silently_share_a_decision_or_invocation(change):
    telemetry = data("telemetry.json")
    if change == "same-decision":
        spans(telemetry).append(copy.deepcopy(spans(telemetry)[0]))
    else:
        attr(telemetry, 1, "invocation_id", {"stringValue": "synthetic-invocation-1"})
    report = run(telemetry=telemetry)
    assert "reconciliation.span-ambiguous" in codes(report)
    assert report["summary"]["matched_attempts"] < 3
    assert "reconciliation.span-unresolved" in codes(report)
    assert "reconciliation.span-missing" not in codes(report)


@pytest.mark.parametrize(
    "pointer",
    [
        "",
        "/decision_id",
        "/path",
        "/bundles/release-policy/revision",
        "/result",
        "/input",
        "/input/principal",
        "/input/action",
        "/input/resource",
        "/input/context/approved",
        "/input/agentmandate/invocation_id",
    ],
)
@pytest.mark.parametrize("field", ["masked", "erased"])
def test_protected_masked_fields_do_not_become_missing_or_denied_effect_findings(pointer, field):
    records = data("decisions.json")
    records[1][field] = [pointer]
    report = run(records=records, telemetry=data("denied-effect-telemetry.json"))
    assert "reconciliation.decision-untrusted" in codes(report)
    assert "reconciliation.decision-unresolved" in codes(report)
    assert "reconciliation.decision-missing" not in codes(report)
    assert "reconciliation.denied-effect-observed" not in codes(report)
    assert report["attempts"][1]["reported_effect_applied"] is None


def test_unrelated_payload_masking_and_slash_prefixed_paths_preserve_scoped_join():
    records = data("decisions.json")
    records[0]["path"] = "/" + records[0]["path"]
    records[0]["masked"] = ["/input/payload"]
    records[0]["input"]["payload"] = "SYNTHETIC_PAYLOAD_CANARY"
    records[0]["labels"] = {"other": "SYNTHETIC_PAYLOAD_CANARY"}
    report = run(records=records)
    assert not report["findings"]
    assert "SYNTHETIC_PAYLOAD_CANARY" not in json.dumps(report)


@pytest.mark.parametrize("result", [None, "true", 1, {}, []])
def test_non_boolean_native_results_are_unresolved_not_coerced(result):
    records = data("decisions.json")
    records[0]["result"] = result
    assert "reconciliation.decision-untrusted" in codes(run(records=records))


@pytest.mark.parametrize("context", [None, True, [], 0, "context"])
def test_invalid_request_context_is_denied_without_requiring_a_native_engine(context):
    records = data("decisions.json")
    records[0]["input"]["context"] = context
    records[0]["result"] = False
    report = run(records=records)
    assert report["decisions"][0]["expected_export_result"] is False
    assert report["decisions"][0]["observed_result"] is False
    assert report["attempts"][0]["join"] == "matched_within_captured_scope"
    assert codes(report) == {"reconciliation.denied-effect-observed"}


@pytest.mark.parametrize("change", ["id", "path", "correlation", "bundle", "run", "invocation"])
def test_missing_native_joins_are_visible(change):
    records = data("decisions.json")
    row = records[0]
    if change == "id":
        del row["decision_id"]
    elif change == "path":
        del row["path"]
    elif change == "correlation":
        del row["input"]["agentmandate"]
    elif change == "bundle":
        del row["bundles"]
    else:
        del row["input"]["agentmandate"][change + "_id"]
    report = run(records=records)
    assert report["findings"]
    assert report["summary"]["matched_attempts"] == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("manifest_sha256", "0" * 64),
        ("configuration_sha256", "0" * 64),
        ("manifest_version", True),
        ("gateway", "another"),
    ],
)
def test_native_joins_cannot_be_relabelled(field, value):
    records = data("decisions.json")
    records[0]["input"]["agentmandate"][field] = value
    report = run(records=records)
    assert "reconciliation.decision-join-mismatch" in codes(report)
    assert not report["decisions"][0]["eligible"]


def test_wrong_bundle_revision_and_false_policy_decision_have_distinct_findings():
    records = data("decisions.json")
    records[0]["bundles"]["release-policy"]["revision"] = "old-policy"
    records[1]["result"] = True
    report = run(records=records)
    assert "reconciliation.decision-revision-mismatch" in codes(report)
    assert "reconciliation.decision-contradiction" in codes(report)
    assert report["decisions"][1]["expected_export_result"] is False
    assert report["decisions"][1]["observed_result"] is True


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "invocation_id",
        "manifest_sha256",
        "configuration_sha256",
        "gateway",
        "policy_revision",
        "principal",
        "action",
        "resource",
    ],
)
def test_span_joins_reject_cross_run_identity_request_and_revision_changes(field):
    telemetry = data("telemetry.json")
    attr(telemetry, 0, field, {"stringValue": "different"})
    report = run(telemetry=telemetry)
    assert "reconciliation.span-join-mismatch" in codes(report)
    assert report["attempts"][0]["reported_effect_applied"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("approved", {"stringValue": "true"}),
        ("effect_applied", {"doubleValue": 1}),
        ("manifest_version", {"boolValue": True}),
        ("decision_id", {"stringValue": ""}),
    ],
)
def test_untyped_or_truthy_span_attributes_cannot_authorize_a_join(field, value):
    telemetry = data("telemetry.json")
    attr(telemetry, 0, field, value)
    report = run(telemetry=telemetry)
    assert "reconciliation.span-field-unresolved" in codes(report)
    assert report["summary"]["matched_attempts"] == 2


def test_unknown_tool_and_wrong_approval_or_request_stay_unresolved():
    telemetry = data("telemetry.json")
    next(a for a in spans(telemetry)[0]["attributes"] if a["key"] == "gen_ai.tool.name")[
        "value"
    ] = {"stringValue": "undeclared"}
    attr(telemetry, 1, "approved", {"boolValue": True})
    records = data("decisions.json")
    records[2]["input"]["resource"] = "another-resource"
    attr(telemetry, 2, "resource", {"stringValue": "another-resource"})
    report = run(records=records, telemetry=telemetry)
    assert {
        "reconciliation.tool-undeclared",
        "reconciliation.span-approval-mismatch",
        "reconciliation.span-request-mismatch",
    } <= codes(report)
    assert report["summary"]["matched_attempts"] == 0


def test_non_tool_spans_and_unrelated_policy_events_have_explicit_counts():
    telemetry = data("telemetry.json")
    spans(telemetry).append({"name": "other", "attributes": []})
    records = data("decisions.json")
    records.append({"path": "other/allow", "decision_id": "unrelated"})
    report = run(records=records, telemetry=telemetry)
    assert not report["findings"]
    assert report["summary"]["decision_events"] == 4
    assert report["summary"]["ignored_decisions"] == 1
    assert report["summary"]["total_spans"] == 4
    assert report["summary"]["tool_attempts"] == 3


def test_ndjson_telemetry_does_not_use_wall_clock_ordering():
    telemetry = data("telemetry.json")
    spans(telemetry)[0].update(startTimeUnixNano="999", endTimeUnixNano="1")
    other = {"resourceSpans": []}
    # NDJSON uses one request per line, not pretty-printed concatenated documents.
    content = json.dumps(telemetry).encode() + b"\n\n" + json.dumps(other).encode()
    mapping = data("mapping.json")
    mapping["pins"]["telemetry"] = hashlib.sha256(content).hexdigest()
    report = reconcile(
        MANIFEST,
        CONFIG,
        (EXAMPLE / "decisions.json").read_bytes(),
        content,
        encode(mapping),
        root=ROOT,
        as_of="2026-10-11",
    )
    assert not report["findings"]
    assert report["ordering"] == "not_assessed"
    assert report["summary"]["matched_attempts"] == 3


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "bool-version",
        "fields",
        "input-key",
        "attributes",
        "duplicate-attribute",
        "coverage",
        "window",
        "pins",
    ],
)
def test_malformed_mapping_is_usage_error(change):
    mapping = data("mapping.json")
    if change in ("version", "bool-version"):
        mapping["reconcile_version"] = 2 if change == "version" else True
    elif change == "fields":
        mapping["extra"] = True
    elif change == "input-key":
        mapping["input_key"] = "a/b"
    elif change == "attributes":
        del mapping["attributes"]["gateway"]
    elif change == "duplicate-attribute":
        mapping["attributes"]["gateway"] = mapping["attributes"]["principal"]
    elif change == "coverage":
        mapping["coverage"]["decisions"] = "almost"
    elif change == "window":
        mapping["expires"] = "2026-10-10"
    else:
        mapping["pins"]["decisions"] = "hash"
    with pytest.raises(ValueError):
        run(mapping=mapping, repin=False)


@pytest.mark.parametrize(
    "telemetry",
    [
        None,
        {},
        {"resourceSpans": [None]},
        {"resourceSpans": [{"scopeSpans": {}}]},
        {"resourceSpans": [{"scopeSpans": [None]}]},
        {"resourceSpans": [{"scopeSpans": [{"spans": {}}]}]},
        {"resourceSpans": [{"scopeSpans": [{"spans": [None]}]}]},
    ],
)
def test_malformed_otlp_containers_are_usage_errors(telemetry):
    with pytest.raises(ValueError):
        run(telemetry={} if telemetry is None else telemetry)


@pytest.mark.parametrize(
    "change", ["attribute-array", "attribute", "key", "value", "duplicate", "tool"]
)
def test_malformed_otlp_attributes_never_use_last_writer_wins(change):
    telemetry = data("telemetry.json")
    span = spans(telemetry)[0]
    if change == "attribute-array":
        span["attributes"] = {}
    elif change == "attribute":
        span["attributes"].append(None)
    elif change == "key":
        span["attributes"].append({"key": 1, "value": {"stringValue": "x"}})
    elif change == "value":
        span["attributes"][0]["value"] = {"stringValue": "execute_tool", "boolValue": True}
    elif change == "duplicate":
        span["attributes"].append(copy.deepcopy(span["attributes"][0]))
    else:
        span["attributes"] = [a for a in span["attributes"] if a["key"] != "gen_ai.tool.name"]
    with pytest.raises(ValueError):
        run(telemetry=telemetry)


@pytest.mark.parametrize("records", [{}, [None], [0]])
def test_malformed_opa_container_is_usage_error(records):
    with pytest.raises(ValueError):
        run(records=records)


@pytest.mark.parametrize("mask", [{}, [0], ["invalid-pointer"]])
def test_malformed_masking_metadata_is_usage_error(mask):
    records = data("decisions.json")
    records[0]["masked"] = mask
    with pytest.raises(ValueError):
        run(records=records)


def test_empty_raw_telemetry_and_foreign_cedar_target_are_usage_errors():
    with pytest.raises(ValueError, match="empty"):
        reconcile(
            MANIFEST,
            CONFIG,
            b"[]",
            b"",
            encode(data("mapping.json")),
            root=ROOT,
            as_of="2026-10-11",
        )
    config = (ROOT / "examples/deployment-drift/cedar-aligned.json").read_bytes()
    with pytest.raises(ValueError, match="Rego/OPA only"):
        run(config=config)


def test_export_mapping_changed_between_reads_cannot_be_consumed(monkeypatch):
    monkeypatch.setattr("agentmandate._deployment_reconcile._read", lambda *args: b"{}")
    with pytest.raises(ValueError, match="changed during"):
        run()


def test_complete_joins_cannot_erase_uncompiled_budgets_or_baseline_breaches(tmp_path):
    config = json.loads(CONFIG)
    for field in ("mapping", "receipt"):
        (tmp_path / f"{field}.json").write_bytes((ROOT / config["export"][field]).read_bytes())
        config["export"][field] = f"{field}.json"
    for artifact, locator in config["policy"]["files"].items():
        (tmp_path / artifact).write_bytes((ROOT / locator).read_bytes())
        config["policy"]["files"][artifact] = artifact
    manifest = json.loads(MANIFEST)
    manifest["limits"] = {"effects": {"irreversible": 0}}
    source = encode(manifest)
    config_content = encode(config)
    receipt = export(source, (tmp_path / "mapping.json").read_bytes(), allow_partial=True)
    (tmp_path / "receipt.json").write_bytes(encode(receipt))
    records = data("decisions.json")
    telemetry = data("telemetry.json")
    for field, content in (("manifest_sha256", source), ("configuration_sha256", config_content)):
        digest = hashlib.sha256(content).hexdigest()
        for i, record in enumerate(records):
            record["input"]["agentmandate"][field] = digest
            attr(telemetry, i, field, {"stringValue": digest})
    report = run(
        records=records, telemetry=telemetry, manifest=source, config=config_content, root=tmp_path
    )
    assert codes(report) == {"deployment.control-uncompiled"}
    assert report["summary"]["matched_attempts"] == 3
    assert report["deployment"]["authority"] == analyse(loads(source.decode())).as_dict()
    assert report["deployment"]["authority"]["breaches"]


def test_cli_clean_json_denied_effect_human_and_missing_input_exit_codes(capsys, tmp_path):
    argv = [
        "deployment",
        "reconcile",
        str(EXAMPLE / "manifest.json"),
        "--config",
        str(EXAMPLE / "config.json"),
        "--root",
        str(ROOT),
        "--decisions",
        str(EXAMPLE / "decisions.json"),
        "--otel",
        str(EXAMPLE / "telemetry.json"),
        "--mapping",
        str(EXAMPLE / "mapping.json"),
        "--as-of",
        "2026-10-11",
        "--json",
    ]
    assert main(argv) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["schema"] == "agentmandate.deployment-reconcile/v2"
    assert not captured.err
    broken = argv.copy()
    broken[broken.index("--otel") + 1] = str(EXAMPLE / "denied-effect-telemetry.json")
    broken[broken.index("--mapping") + 1] = str(EXAMPLE / "denied-effect-mapping.json")
    broken.remove("--json")
    assert main(broken) == 1
    assert "reconciliation.denied-effect-observed" in capsys.readouterr().out
    argv[argv.index("--decisions") + 1] = str(tmp_path / "missing")
    assert main(argv) == 2
    captured = capsys.readouterr()
    assert not captured.out and captured.err.startswith("error:")


def test_subset_comparator_matches_native_opa_on_export_cases_and_malformed_requests(tmp_path):
    binary = os.environ.get("AGENTMANDATE_OPA") or shutil.which("opa")
    if not binary:
        if os.environ.get("AGENTMANDATE_REQUIRE_OPA_NATIVE"):
            pytest.fail("native OPA is required")
        pytest.skip("native OPA not installed")
    config = json.loads(CONFIG)
    compiled = export(MANIFEST, (ROOT / config["export"]["mapping"]).read_bytes())
    baseline = run()["deployment"]
    cases = [row["request"] for row in compiled["tests"]]
    cases.extend([None, {}, {"context": {}}, {"principal": 1, "context": {}}])
    valid = compiled["tests"][0]["request"]
    for context in (None, True, {"approved": 1}, {"approved": "true"}, {}):
        cases.append({**valid, "context": context})
    policy = tmp_path / "policy.rego"
    policy.write_text(compiled["policy"])
    request_path = tmp_path / "input.json"
    for request in cases:
        request_path.write_bytes(encode(request))
        result = subprocess.run(
            [
                binary,
                "eval",
                "--format",
                "json",
                "--data",
                str(policy),
                "--input",
                str(request_path),
                "data.release_gate.allow",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        native = json.loads(result.stdout)["result"][0]["expressions"][0]["value"]
        assert _expected(request, baseline["tools"]) is native
