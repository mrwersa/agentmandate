import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentmandate._continuity import ContinuityFormatError
from agentmandate._principal_accounting import (
    PrincipalAccountingBinding,
    analyse_principal_accounting,
)
from agentmandate._principal_continuity import PrincipalContinuity
from agentmandate.cli import main
from agentmandate.manifest import loads
from agentmandate.reach import analyse

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/principal-continuity"
AS_OF = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


def _raw(name="accounting-binding"):
    return json.loads((EXAMPLE / f"{name}.json").read_text())


def _pin(binding, profile):
    binding["profile_sha256"] = hashlib.sha256(
        PrincipalContinuity.from_json(json.dumps(profile)).to_json().encode()
    ).hexdigest()


def _run(binding=None, profile=None, *, contents=None, binding_contents=None,
         when=AS_OF, manifest=None, mandate=None, depth=None):
    manifest = (EXAMPLE / "manifest.json").read_bytes() if manifest is None else manifest
    return analyse_principal_accounting(
        loads(manifest.decode()) if mandate is None else mandate,
        PrincipalContinuity.from_json(json.dumps(_raw("profile") if profile is None else profile)),
        {"observations.json": (EXAMPLE / "observations.json").read_bytes()}
        if contents is None else contents,
        PrincipalAccountingBinding.from_json(json.dumps(_raw() if binding is None else binding)),
        {"accounting-review.json": (EXAMPLE / "accounting-review.json").read_bytes()}
        if binding_contents is None else binding_contents,
        as_of=when, mandate_bytes=manifest, depth=depth,
    )


def _codes(result):
    return {finding["code"] for finding in result["findings"]}


def _assert_withheld(result):
    assert "continuity.shared-mandate-unresolved" in _codes(result)
    assert "continuity.observed-budget-exceeded" not in _codes(result)
    for trial in result["trials"]:
        assert trial["accounting"] == {
            "status": "unresolved", "account": None, "observed_completed": None,
            "limit": None, "budget": "unresolved",
        }
        assert trial["mandate_identity"] == "unresolved"
        assert trial["state"] == trial["admission"] == trial["safe_continuation"] == "unresolved"


def test_reviewed_accounting_reports_breach_without_claiming_reset_or_safety():
    result = _run()
    assert result["schema"] == "agentmandate.principal-accounting/v1"
    assert result["binding_eligible"] is result["observations_eligible"] is True
    binding = PrincipalAccountingBinding.from_json(json.dumps(_raw()))
    assert result["binding"] == binding.body
    assert result["binding_sha256"] == hashlib.sha256(binding.to_json().encode()).hexdigest()
    trials = {t["id"]: t for t in result["trials"]}
    changed = trials["changed-principal-same-session"]
    assert changed["observed_completed_by_principal"] == {"a": 600, "b": 600}
    assert changed["accounting"]["observed_completed"] == 1200
    assert changed["accounting"]["budget"] == "exceeded_by_observed_calls"
    assert trials["same-principal-fresh-session"]["accounting"]["observed_completed"] == 1200
    same = trials["same-principal-same-session"]
    assert same["accounting"]["observed_completed"] == 600
    assert same["accounting"]["budget"] == "not_exceeded_by_observed_calls"
    assert len({t["accounting"]["account"] for t in result["trials"]}) == 3
    assert "observed_completed" not in result  # No cross-trial sum.
    assert "continuity.shared-mandate-unresolved" not in _codes(result)
    assert "continuity.continuation-unresolved" in _codes(result)
    for trial in result["trials"]:
        assert trial["mandate_identity"] == "bound_by_review"
        assert trial["state"] == trial["admission"] == trial["safe_continuation"] == "unresolved"
    assert result["authority"] == analyse(loads((EXAMPLE / "manifest.json").read_text())).as_dict()
    assert PrincipalAccountingBinding.from_json(binding.to_json()).to_json() == binding.to_json()


@pytest.mark.parametrize("amount", [0, 500, 501])
def test_inclusive_limit_and_zero_amounts(amount):
    profile, binding = _raw("profile"), _raw()
    for trial in profile["trials"]:
        for call in trial["calls"]:
            call["amount"] = amount
    _pin(binding, profile)
    result = _run(binding, profile)
    accounting = result["trials"][0]["accounting"]
    assert accounting["observed_completed"] == amount * 2
    assert accounting["budget"] == (
        "exceeded_by_observed_calls" if amount == 501 else "not_exceeded_by_observed_calls"
    )


def test_unknown_completion_withholds_only_affected_trial_and_keeps_other_boundaries():
    profile, binding = _raw("profile"), _raw()
    profile["trials"][1]["calls"][1]["completion"] = "unknown"
    _pin(binding, profile)
    result = _run(binding, profile)
    assert result["binding_eligible"] is True
    trial = result["trials"][0]
    assert trial["observed_completed_by_principal"] == {"a": 600, "b": 0}
    assert trial["accounting"]["observed_completed"] is None
    assert trial["mandate_identity"] == "unresolved"
    assert result["trials"][1]["accounting"]["observed_completed"] == 1200
    assert "continuity.shared-mandate-unresolved" in _codes(result)


def test_sum_does_not_invent_order_or_known_session_and_honors_depth():
    profile, binding = _raw("profile"), _raw()
    for trial in profile["trials"]:
        trial["ordering"] = "unknown"
        for call in trial["calls"]:
            call["session"] = None
    _pin(binding, profile)
    result = _run(binding, profile, depth=1)
    assert result["trials"][0]["accounting"]["observed_completed"] == 1200
    assert result["trials"][0]["ordering"] == "unknown"
    assert result["trials"][0]["relations"] == [{"principal": "changed", "session": "unknown"}]
    assert result["authority"] == analyse(
        loads((EXAMPLE / "manifest.json").read_text()), depth=1,
    ).as_dict()


@pytest.mark.parametrize("side", ["profile", "binding"])
@pytest.mark.parametrize("state", ["unreviewed", "contested", "heuristic", "expired"])
def test_reviews_are_independent_and_neither_acceptance_can_substitute(side, state):
    profile, binding = _raw("profile"), _raw()
    evidence = (profile if side == "profile" else binding)["evidence"]
    if state == "unreviewed":
        evidence.update(review=state, reviewer=None, expires=None)
    elif state == "contested":
        evidence["review"] = state
    elif state == "heuristic":
        evidence["confidence"] = state
    else:
        evidence["expires"] = "2026-10-08"
    _pin(binding, profile)
    result = _run(binding, profile)
    _assert_withheld(result)
    assert result["binding_eligible"] is (side == "profile")
    assert result["observations_eligible"] is (side == "binding")


@pytest.mark.parametrize("side", ["contents", "binding_contents"])
@pytest.mark.parametrize("state", ["missing", "extra", "tampered"])
def test_source_bytes_are_required_on_both_sides(side, state):
    locator = "observations.json" if side == "contents" else "accounting-review.json"
    contents = {locator: (EXAMPLE / locator).read_bytes()}
    if state == "missing":
        contents.clear()
    elif state == "extra":
        contents["extra"] = b"extra"
    else:
        contents[locator] += b" "
    result = _run(**{side: contents})
    _assert_withheld(result)
    code = "continuity.source-untrusted" if side == "contents" else (
        "continuity.accounting-source-untrusted"
    )
    assert code in _codes(result)


@pytest.mark.parametrize(
    ("timestamp", "eligible"),
    [("2026-11-08T23:59:59+00:00", True), ("2026-11-09T00:00:00+00:00", False)],
)
def test_binding_and_observation_expiry_use_inclusive_utc_date(timestamp, eligible):
    result = _run(when=datetime.fromisoformat(timestamp))
    assert result["binding_eligible"] is result["observations_eligible"] is eligible
    if not eligible:
        _assert_withheld(result)
        assert "continuity.accounting-evidence-untrusted" in _codes(result)
        assert "continuity.evidence-untrusted" in _codes(result)


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(manifest_sha256="0" * 64),
    lambda b: b.update(profile_sha256="0" * 64),
    lambda b: b.update(provider="other"),
    lambda b: b.update(boundary="other"),
    lambda b: b["measurement"].update(profile_tool="other"),
    lambda b: b["measurement"].update(dimension="cost"),
    lambda b: b["measurement"].update(unit="USD"),
    lambda b: b["measurement"].update(manifest_tool="missing"),
    lambda b: b["measurement"].update(manifest_tool="open_case"),
    lambda b: b["measurement"].update(value_arg="different"),
    lambda b: b["limit"].update(amount=1200),
    lambda b: b["limit"].update(unit="USD"),
    lambda b: b["principals"].pop(),
    lambda b: b["principals"][0].update(alias="other"),
    lambda b: b["principals"][0].update(manifest_principal="service"),
    lambda b: b["trials"].pop(),
    lambda b: b["trials"][0].update(id="other"),
    lambda b: b["trials"][0]["executions"][0].update(pointer="/different"),
    lambda b: b["trials"][0]["executions"][0].update(source="other"),
    lambda b: b["mediation"].update(kind="unknown"),
])
def test_each_binding_join_gap_withholds_all_shared_totals(mutate):
    binding = _raw()
    mutate(binding)
    result = _run(binding)
    _assert_withheld(result)
    assert result["binding_eligible"] is False
    assert "continuity.accounting-binding-mismatch" in _codes(result)


@pytest.mark.parametrize("mutation", ["no_total", "fractional_total", "currency", "tool_currency"])
def test_actual_manifest_contract_is_checked_not_only_binding_digest(mutation):
    manifest, binding = _raw("manifest"), _raw()
    if mutation == "no_total":
        manifest["limits"].pop("total")
    elif mutation == "fractional_total":
        manifest["limits"]["total"]["amount"] = 1000.5
    elif mutation == "currency":
        manifest["limits"]["total"]["currency"] = "USD"
    else:
        manifest["tools"][1]["ceiling"]["currency"] = "USD"
    data = json.dumps(manifest).encode()
    binding["manifest_sha256"] = hashlib.sha256(data).hexdigest()
    _assert_withheld(_run(binding, manifest=data))


@pytest.mark.parametrize("data", [b"not JSON", b"\xff", b"{}"])
def test_direct_consumer_refuses_forged_manifest_bytes(data):
    _assert_withheld(_run(manifest=data, mandate=loads((EXAMPLE / "manifest.json").read_text())))


def test_direct_consumer_reparses_mutable_records_and_checks_object_byte_agreement():
    manifest = (EXAMPLE / "manifest.json").read_bytes()
    other = _raw("manifest")
    other["agent"] = "other"
    _assert_withheld(_run(manifest=manifest, mandate=loads(json.dumps(other))))
    binding = PrincipalAccountingBinding.from_json(json.dumps(_raw()))
    binding.body["limit"]["amount"] = True
    with pytest.raises(ContinuityFormatError):
        analyse_principal_accounting(
            loads(manifest.decode()),
            PrincipalContinuity.from_json(json.dumps(_raw("profile"))), {}, binding, {},
            as_of=AS_OF, mandate_bytes=manifest,
        )


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(principal_accounting_binding_version=2),
    lambda b: b.update(principal_accounting_binding_version=True),
    lambda b: b.update(extra="unknown"),
    lambda b: b.pop("intent"),
    lambda b: b.update(manifest_sha256="ABC"),
    lambda b: b["limit"].update(amount=True),
    lambda b: b["limit"].update(amount=-1),
    lambda b: b["limit"].update(amount=1.2),
    lambda b: b["limit"].update(comparison="strict"),
    lambda b: b["limit"].update(scope="all_trials"),
    lambda b: b["intent"].update(kind="same_session"),
    lambda b: b["intent"].update(statement=""),
    lambda b: b["intent"].update(sources=["missing"]),
    lambda b: b["mediation"].update(kind="gateway_only"),
    lambda b: b["mediation"].update(kind=[]),
    lambda b: b["mediation"].update(sources=[]),
    lambda b: b["principals"].append(b["principals"][0]),
    lambda b: b["principals"][0].update(subject=""),
    lambda b: b["principals"][0].update(sources=["missing"]),
    lambda b: b["trials"].append(b["trials"][0]),
    lambda b: b["trials"][1].update(account=b["trials"][0]["account"]),
    lambda b: b["trials"][0].update(executions=[]),
    lambda b: b["trials"][0]["executions"][1].update(id=b["trials"][0]["executions"][0]["id"]),
    lambda b: b["trials"][1]["executions"][0].update(id=b["trials"][0]["executions"][0]["id"]),
    lambda b: b["trials"][0]["executions"][1].update(
        source=b["trials"][0]["executions"][0]["source"],
        pointer=b["trials"][0]["executions"][0]["pointer"],
    ),
    lambda b: b["trials"][0].update(sources=["missing"]),
])
def test_strict_binding_rejects_ambiguous_or_unsupported_input(mutate):
    binding = _raw()
    mutate(binding)
    with pytest.raises(ContinuityFormatError):
        PrincipalAccountingBinding.from_json(json.dumps(binding))


def _args():
    return [
        "continuity", "reconcile", str(EXAMPLE / "manifest.json"),
        "--continuity-provider", str(EXAMPLE / "profile.json"),
        "--continuity-source", f"observations.json={EXAMPLE / 'observations.json'}",
        "--continuity-binding", str(EXAMPLE / "accounting-binding.json"),
        "--continuity-binding-source",
        f"accounting-review.json={EXAMPLE / 'accounting-review.json'}",
        "--continuity-as-of", "2026-10-09T12:00:00Z",
    ]


def test_cli_validates_binding_and_reports_accounting_without_green_exit(capsys):
    assert main(["continuity", "validate", str(EXAMPLE / "accounting-binding.json")]) == 0
    assert capsys.readouterr().out == "valid principal accounting binding v1\n"
    assert main([*_args(), "--json"]) == 1
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out) == _run()
    assert main(_args()) == 1
    output = capsys.readouterr()
    assert not output.err
    assert "REVIEWED ACCOUNTING" in output.out
    assert "'observed_completed': 1200" in output.out
    assert "AUTHORITY" in output.out


@pytest.mark.parametrize(("name", "timestamp"), [
    ("eligible", "2026-10-09T12:00:00Z"), ("expired", "2026-11-09T00:00:00Z"),
])
def test_cli_pins_complete_new_result_without_replacing_observation_v1(name, timestamp, capsys):
    args = _args()
    args[-1] = timestamp
    assert main([*args, "--json"]) == 1
    output = capsys.readouterr()
    assert not output.err
    expected = ROOT / "tests/fixtures" / f"principal-accounting-result-v1-{name}.json"
    assert output.out.encode() == expected.read_bytes()


@pytest.mark.parametrize("options", [
    ["--continuity-binding", str(EXAMPLE / "profile.json")],
    ["--continuity-binding", str(ROOT / "examples/continuity-refund/binding.json")],
    ["--continuity-provider", str(EXAMPLE / "accounting-binding.json")],
    ["--continuity-provider", str(ROOT / "examples/continuity-refund/provider.json")],
    ["--continuity-binding-source", "extra=missing.json"],
    ["--ir"], ["--graph"],
])
def test_cli_refuses_wrong_artifact_composition_and_extra_sources(options, capsys):
    assert main([*_args(), *options, "--json"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


def test_cli_malformed_binding_and_missing_sources_are_usage_failures(tmp_path, capsys):
    path = tmp_path / "binding.json"
    raw = _raw()
    raw["principals"][0]["subject"] = ""
    path.write_text(json.dumps(raw))
    assert main([*_args(), "--continuity-binding", str(path), "--json"]) == 2
    assert capsys.readouterr().out == ""
    args = _args()
    del args[9:11]
    assert main(args) == 2
    assert capsys.readouterr().out == ""


def test_cli_explains_accounting_binding_and_provider_type_mismatch(capsys):
    assert main([
        *_args(), "--continuity-provider",
        str(ROOT / "examples/continuity-refund/provider.json"), "--json",
    ]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "this provider profile requires a continuity binding" in output.err
    assert "principal accounting bindings require a principal profile" in output.err


def test_cli_tampered_binding_source_is_finding_with_complete_output(tmp_path, capsys):
    path = tmp_path / "review.json"
    path.write_text("tampered")
    args = _args()
    args[10] = f"accounting-review.json={path}"
    assert main([*args, "--json"]) == 1
    output = capsys.readouterr()
    assert not output.err
    _assert_withheld(json.loads(output.out))


def test_canonical_binding_ignores_mapping_order_but_not_claims():
    raw = _raw()
    baseline = PrincipalAccountingBinding.from_json(json.dumps(raw)).to_json()
    raw["principals"].reverse()
    raw["trials"].reverse()
    for trial in raw["trials"]:
        trial["executions"].reverse()
    assert PrincipalAccountingBinding.from_json(json.dumps(raw)).to_json() == baseline
    raw["intent"]["statement"] += " changed"
    assert PrincipalAccountingBinding.from_json(json.dumps(raw)).to_json() != baseline
