import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentmandate._continuity import ContinuityFormatError
from agentmandate._scalar_handover import (
    ScalarHandover,
    _admission_witness,
    analyse_scalar_handover,
)
from agentmandate.cli import main
from agentmandate.manifest import loads
from agentmandate.reach import analyse

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/scalar-handover"
MANIFEST = ROOT / "examples/continuity-refund/manifest.json"
AS_OF = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _raw(name="handover"):
    return json.loads((EXAMPLE / f"{name}.json").read_text())


def _contents(raw):
    return {s["locator"]: (ROOT / s["locator"]).read_bytes() for s in raw["sources"]}


def _run(raw=None, *, contents=None, when=AS_OF, depth=None, manifest=None, mandate=None):
    raw = _raw() if raw is None else raw
    data = MANIFEST.read_bytes() if manifest is None else manifest
    return analyse_scalar_handover(
        loads(data.decode()) if mandate is None else mandate,
        ScalarHandover.from_json(json.dumps(raw)),
        _contents(raw) if contents is None else contents,
        as_of=when,
        mandate_bytes=data,
        depth=depth,
    )


def _codes(result):
    return {f["code"] for f in result["findings"]}


def _policy_change(raw, contents, side, **changes):
    source = next(s for s in raw["sources"] if s["id"] == raw["policies"][side])
    policy = json.loads(contents[source["locator"]])
    policy.update(changes)
    contents[source["locator"]] = json.dumps(policy).encode()
    digest = hashlib.sha256(contents[source["locator"]]).hexdigest()
    source["content_sha256"] = digest
    binding = raw["bindings"][side]
    binding["enforcement"]["policy_sha256"] = digest
    for nested in binding["sources"]:
        if nested["locator"] == source["locator"]:
            nested["content_sha256"] = digest


def _manifest_change(raw, manifest):
    data = json.dumps(manifest).encode()
    digest = hashlib.sha256(data).hexdigest()
    raw["manifest_sha256"] = digest
    for binding in raw["bindings"].values():
        binding["mandate"]["sha256"] = digest
    return data


def test_retained_state_proves_useful_tightening_in_declared_model():
    result = _run()
    assert result["schema"] == "agentmandate.scalar-handover/v1"
    assert result["evidence_eligible"] is True
    assert not result["findings"]
    assert result["proof"] == {
        "verdict": "satisfied_for_declared_scalar_handover",
        "admission_inclusion": "established_for_scalar_model",
        "remaining_before": 300,
        "remaining_after": 200,
        "successor_only_amount": None,
        "scope": "All nonnegative integer next requests in the declared scalar model at cutover.",
    }
    assert "safe_continuation" not in result
    assert result["authority"] == analyse(loads(MANIFEST.read_text())).as_dict()
    handover = ScalarHandover.from_json(json.dumps(_raw()))
    assert result["handover_sha256"] == hashlib.sha256(handover.to_json().encode()).hexdigest()
    assert ScalarHandover.from_json(handover.to_json()).to_json() == handover.to_json()


def test_complete_integer_inclusion_matches_independent_enumeration_including_zero():
    for before in range(-4, 10):
        predecessor = {q for q in range(15) if q <= before}
        for after in range(-4, 10):
            successor = {q for q in range(15) if q <= after}
            difference = successor - predecessor
            assert _admission_witness(before, after) == (min(difference) if difference else None)


@pytest.mark.parametrize(
    ("name", "code", "witness"),
    [
        ("handover-reset", "handover.completed-state-lost", 301),
        ("handover-lost-reservation", "handover.pending-state-changed", None),
    ],
)
def test_reset_and_lost_pending_state_are_not_hidden_by_tightening(name, code, witness):
    result = _run(_raw(name))
    assert result["proof"]["verdict"] == "violated_for_declared_scalar_handover"
    assert code in _codes(result)
    assert result["proof"]["successor_only_amount"] == witness


@pytest.mark.parametrize("after", [600, 650, 1000])
def test_conservative_completed_accounting_and_empty_future_domain(after):
    raw = _raw()
    raw["state"]["completed_after"] = after
    result = _run(raw)
    assert result["proof"]["verdict"] == "satisfied_for_declared_scalar_handover"
    assert result["proof"]["remaining_after"] == 900 - after - 100
    assert result["proof"]["successor_only_amount"] is None


def test_zero_request_is_a_witness_when_empty_predecessor_domain_reopens():
    raw = _raw()
    raw["state"].update(completed_before=1100, completed_after=800)
    result = _run(raw)
    assert result["proof"]["remaining_before"] == -200
    assert result["proof"]["remaining_after"] == 0
    assert result["proof"]["successor_only_amount"] == 0
    assert "handover.admission-widens" in _codes(result)


def test_limit_increase_is_refused_even_when_extra_consumption_hides_admission_widening():
    raw = _raw()
    contents = _contents(raw)
    _policy_change(raw, contents, "after", limit=1200)
    raw["state"]["completed_after"] = 1000
    result = _run(raw, contents=contents)
    assert result["proof"]["successor_only_amount"] is None
    assert result["proof"]["verdict"] == "violated_for_declared_scalar_handover"
    assert _codes(result) == {"handover.limit-widens"}


@pytest.mark.parametrize(
    "field", ["completed_before", "completed_after", "pending_before", "pending_after"]
)
def test_unknown_state_withholds_proof_instead_of_assuming_zero(field):
    raw = _raw()
    raw["state"][field] = None
    result = _run(raw)
    assert result["proof"]["verdict"] == "unresolved"
    assert result["proof"]["remaining_after"] is None
    assert "handover.state-unresolved" in _codes(result)


@pytest.mark.parametrize("field", ["predecessor_fenced", "successor_exclusive"])
@pytest.mark.parametrize("value", [False, None])
def test_unestablished_fencing_cannot_prove_conformance(field, value):
    raw = _raw()
    raw["fence"][field] = value
    assert _run(raw)["proof"]["verdict"] == "unresolved"


@pytest.mark.parametrize("side", ["root", "before", "after"])
@pytest.mark.parametrize("state", ["unreviewed", "contested", "heuristic", "expired"])
def test_three_reviews_are_independent(side, state):
    raw = _raw()
    evidence = (raw if side == "root" else raw["bindings"][side])["evidence"]
    if state == "unreviewed":
        evidence.update(review=state, reviewer=None, expires=None)
    elif state == "contested":
        evidence["review"] = state
    elif state == "heuristic":
        evidence["confidence"] = state
    else:
        evidence["expires"] = "2026-10-09"
    result = _run(raw)
    assert result["evidence_eligible"] is False
    assert result["proof"]["verdict"] == "unresolved"
    assert result["proof"]["successor_only_amount"] is None


@pytest.mark.parametrize(
    "change",
    ["missing", "extra", "tampered", "invalid-policy", "unsupported-policy", "unicode-policy"],
)
def test_source_and_model_failures_never_establish_a_proof(change):
    raw = _raw()
    contents = _contents(raw)
    source = next(s for s in raw["sources"] if s["id"] == "after-policy")
    locator = source["locator"]
    if change == "missing":
        contents.pop(locator)
    elif change == "extra":
        contents["extra"] = b"extra"
    elif change == "tampered":
        contents[locator] += b" "
    elif change == "unsupported-policy":
        _policy_change(raw, contents, "after", accounting="completed_only")
    else:
        contents[locator] = b"invalid" if change == "invalid-policy" else b"\xff"
        digest = hashlib.sha256(contents[locator]).hexdigest()
        source["content_sha256"] = digest
        raw["bindings"]["after"]["enforcement"]["policy_sha256"] = digest
        raw["bindings"]["after"]["sources"][0]["content_sha256"] = digest
    assert _run(raw, contents=contents)["proof"]["verdict"] == "unresolved"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(manifest_sha256="0" * 64),
        lambda r: r.update(cutover_at="2026-10-11T00:00:00Z"),
        lambda r: r["bindings"]["after"]["enforcement"].update(policy_sha256="0" * 64),
        lambda r: r["bindings"]["after"]["sources"][0].update(kind="other"),
        lambda r: r["bindings"]["after"]["mandate"].update(sha256="0" * 64),
        lambda r: r["bindings"]["after"]["mandate"].update(principal="service"),
        lambda r: r["bindings"]["after"]["mediation"].update(kind="exclusive_adapter"),
        lambda r: r["bindings"]["before"]["validity"].update(issued_at="2026-10-10T00:00:01Z"),
        lambda r: r["bindings"]["before"]["validity"].update(expires_at="2026-10-10T00:00:00Z"),
        lambda r: r["bindings"]["after"].update(id=r["bindings"]["before"]["id"]),
        lambda r: r["bindings"]["after"]["enforcement"].update(binding="synthetic-before"),
        lambda r: r["bindings"]["after"]["enforcement"].update(provider="other"),
    ],
)
def test_each_binding_and_input_join_gap_is_unresolved(mutate):
    raw = _raw()
    mutate(raw)
    result = _run(raw)
    assert result["proof"]["verdict"] == "unresolved"
    assert result["proof"]["remaining_before"] is None


@pytest.mark.parametrize("changes", [{"tool": "other"}, {"value_arg": "other"}, {"unit": "USD"}])
def test_policies_must_share_the_complete_tool_contract(changes):
    raw = _raw()
    contents = _contents(raw)
    _policy_change(raw, contents, "after", **changes)
    assert "handover.model-unjoined" in _codes(_run(raw, contents=contents))


@pytest.mark.parametrize(
    "change", ["total", "tool", "value_arg", "tool_currency", "total_currency", "multiple_tools"]
)
def test_manifest_semantics_are_checked_after_matching_all_digests(change):
    raw = _raw()
    manifest = json.loads(MANIFEST.read_text())
    if change == "total":
        manifest["limits"].pop("total")
    elif change == "tool":
        manifest["tools"][1]["name"] = "different"
    elif change == "value_arg":
        manifest["tools"][1].pop("value_arg")
        manifest["tools"][1].pop("ceiling")
    elif change == "tool_currency":
        manifest["tools"][1]["ceiling"]["currency"] = "USD"
    elif change == "total_currency":
        manifest["limits"]["total"]["currency"] = "USD"
    else:
        tool = copy.deepcopy(manifest["tools"][1])
        tool["name"] = "another_refund"
        manifest["tools"].append(tool)
    result = _run(raw, manifest=_manifest_change(raw, manifest))
    assert result["proof"]["verdict"] == "unresolved"


def test_valid_predecessor_at_cutover_may_expire_before_evaluation_but_successor_must_not():
    raw = _raw()
    raw["bindings"]["before"]["validity"]["expires_at"] = "2026-10-10T00:00:01Z"
    when = datetime(2026, 10, 10, 0, 0, 2, tzinfo=timezone.utc)
    assert _run(raw, when=when)["proof"]["verdict"] == "satisfied_for_declared_scalar_handover"
    raw["bindings"]["after"]["validity"]["expires_at"] = "2026-10-10T00:00:02Z"
    assert _run(raw, when=when)["proof"]["verdict"] == "unresolved"


def test_manifest_authority_gate_remains_independent_of_a_satisfied_model():
    result = _run(depth=1)
    assert result["proof"]["verdict"] == "satisfied_for_declared_scalar_handover"
    assert result["authority"]["truncated"] is True
    assert "handover.manifest-authority" in _codes(result)
    assert result["authority"] == analyse(loads(MANIFEST.read_text()), depth=1).as_dict()


def test_model_conformance_never_clears_a_manifest_authority_breach():
    raw = _raw()
    manifest = json.loads(MANIFEST.read_text())
    manifest["tools"].append(
        {"name": "ungated_write", "effect": "irreversible", "requires_approval": False}
    )
    data = _manifest_change(raw, manifest)
    result = _run(raw, manifest=data)
    assert result["proof"]["verdict"] == "satisfied_for_declared_scalar_handover"
    assert result["authority"]["breaches"]
    assert "handover.manifest-authority" in _codes(result)
    assert result["authority"] == analyse(loads(data.decode())).as_dict()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(scalar_handover_version=2),
        lambda r: r.update(scalar_handover_version=True),
        lambda r: r.update(extra=True),
        lambda r: r["policies"].update(after="missing"),
        lambda r: r["state"].update(completed_after=True),
        lambda r: r["state"].update(completed_before=-1),
        lambda r: r["state"].update(pending_before="unknown"),
        lambda r: r["state"]["pending_before"].append(r["state"]["pending_before"][0]),
        lambda r: r["state"]["pending_after"][0].update(amount=-1),
        lambda r: r["fence"].update(successor_exclusive="yes"),
        lambda r: r["attestation"].update(statement=""),
        lambda r: r["attestation"].update(sources=["missing"]),
        lambda r: r["bindings"]["after"].update(continuity_binding_version=2),
    ],
)
def test_strict_artifact_refuses_ambiguous_records(mutate):
    raw = _raw()
    mutate(raw)
    with pytest.raises(ContinuityFormatError):
        ScalarHandover.from_json(json.dumps(raw))


def _args(name="handover", when="2026-10-10T00:00:00Z"):
    args = [
        "continuity",
        "handover",
        "examples/continuity-refund/manifest.json",
        str(EXAMPLE / f"{name}.json"),
        "--as-of",
        when,
    ]
    for source in _raw()["sources"]:
        args.extend(["--source", f"{source['locator']}={ROOT / source['locator']}"])
    return args


def test_cli_validation_clean_handover_and_text(capsys):
    assert main(["continuity", "validate", str(EXAMPLE / "handover.json")]) == 0
    assert capsys.readouterr().out == "valid scalar handover v1\n"
    assert main([*_args(), "--json"]) == 0
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out) == _run()
    assert main(_args()) == 0
    output = capsys.readouterr()
    assert "satisfied_for_declared_scalar_handover" in output.out
    assert "AUTHORITY" in output.out


@pytest.mark.parametrize(
    ("fixture", "name", "when", "exit_code"),
    [
        ("retained", "handover", "2026-10-10T00:00:00Z", 0),
        ("reset", "handover-reset", "2026-10-10T00:00:00Z", 1),
        ("expired", "handover", "2026-11-09T00:00:00Z", 1),
    ],
)
def test_cli_fixed_result_baselines(fixture, name, when, exit_code, capsys):
    assert main([*_args(name, when), "--json"]) == exit_code
    output = capsys.readouterr()
    assert not output.err
    assert (
        output.out.encode()
        == (ROOT / f"tests/fixtures/scalar-handover-result-v1-{fixture}.json").read_bytes()
    )


@pytest.mark.parametrize(
    "options",
    [
        ["--source", "extra=missing"],
        ["--source", "bad"],
        ["--as-of", "not UTC"],
    ],
)
def test_cli_usage_errors_emit_no_partial_output(options, capsys):
    assert main([*_args(), *options, "--json"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err
    if "--as-of" in options:
        assert "--as-of must be" in output.err


def test_cli_rejects_ir_composition_at_argument_parsing(capsys):
    with pytest.raises(SystemExit) as exc:
        main([*_args(), "--ir"])
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


def test_cli_rejects_other_artifact_roles_and_missing_source(tmp_path, capsys):
    args = _args()
    args[3] = str(ROOT / "examples/revision-review/review.json")
    assert main(args) == 2
    assert capsys.readouterr().out == ""
    args = _args()
    del args[-2:]
    assert main(args) == 2
    assert capsys.readouterr().out == ""
    args = _args()
    args[3] = str(tmp_path / "missing.json")
    assert main(args) == 2
    assert capsys.readouterr().out == ""


def test_pending_order_is_canonical_and_mutated_records_are_revalidated():
    raw = _raw()
    for side in ["pending_before", "pending_after"]:
        raw["state"][side].append({"id": "pending-0", "amount": 0})
    baseline = ScalarHandover.from_json(json.dumps(raw)).to_json()
    for side in ["pending_before", "pending_after"]:
        raw["state"][side].reverse()
    assert ScalarHandover.from_json(json.dumps(raw)).to_json() == baseline
    handover = ScalarHandover.from_json(baseline)
    handover.body["state"]["completed_after"] = True
    with pytest.raises(ContinuityFormatError):
        analyse_scalar_handover(
            loads(MANIFEST.read_text()),
            handover,
            _contents(raw),
            as_of=AS_OF,
            mandate_bytes=MANIFEST.read_bytes(),
        )
