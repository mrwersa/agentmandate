import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentmandate._continuity import (
    AgentCoreContinuity,
    ContinuityBinding,
    ContinuityFormatError,
    analyse_continuity,
)
from agentmandate._revision_review import RevisionReview, analyse_revision_review
from agentmandate.cli import main
from agentmandate.manifest import loads

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/revision-review"
REFUND = ROOT / "examples/continuity-refund"
AS_OF = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _raw(name="review"):
    return json.loads((EXAMPLE / f"{name}.json").read_text())


def _bytes(artifact):
    return {source.locator: (ROOT / source.locator).read_bytes() for source in artifact.sources}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _run(
    raw=None,
    *,
    provider=None,
    binding=None,
    review_bytes=None,
    provider_bytes=None,
    binding_bytes=None,
    when=AS_OF,
    manifest=None,
    depth=None,
):
    review = RevisionReview.from_json(json.dumps(_raw() if raw is None else raw))
    provider = AgentCoreContinuity.from_json(
        json.dumps(_raw("provider") if provider is None else provider)
    )
    binding = ContinuityBinding.from_json(
        (REFUND / "binding.json").read_text() if binding is None else json.dumps(binding)
    )
    manifest = (REFUND / "manifest.json").read_bytes() if manifest is None else manifest
    return analyse_revision_review(
        loads(manifest.decode(), source="examples/continuity-refund/manifest.json"),
        provider,
        _bytes(provider) if provider_bytes is None else provider_bytes,
        binding,
        _bytes(binding) if binding_bytes is None else binding_bytes,
        review,
        _bytes(review) if review_bytes is None else review_bytes,
        as_of=when,
        mandate_bytes=manifest,
        depth=depth,
    )


def _pin(raw, provider):
    raw["provider_sha256"] = _sha(
        AgentCoreContinuity.from_json(json.dumps(provider)).to_json().encode()
    )


def _assert_unresolved(result):
    for row in result["assessments"]:
        assert row["comparability"] == row["issuer_amendment"] == "unresolved"
        assert row["safe_continuation"] == "unresolved"
        assert row["control_joined"] is False


def test_scoped_claims_do_not_rewrite_baseline_reset_or_authority():
    result = _run()
    assert result["schema"] == "agentmandate.revision-review/v1"
    assert result["review_inputs_eligible"] is True
    assert result["review_sha256"] == _sha(
        RevisionReview.from_json(json.dumps(_raw())).to_json().encode()
    )
    rows = {row["control"]: row for row in result["assessments"]}
    assert rows["equivalent-reset"]["comparability"] == "established_within_reviewed_scope"
    assert rows["tightening-reset"]["relation"] == "tightens"
    assert rows["retaining-amendment"]["issuer_amendment"] == "approved_retaining_state"
    assert rows["equivalent-reset"]["issuer_amendment"] == "not_required_within_reviewed_scope"
    assert all(row["safe_continuation"] == "unresolved" for row in rows.values())
    provider = AgentCoreContinuity.from_json(json.dumps(_raw("provider")))
    binding = ContinuityBinding.from_json((REFUND / "binding.json").read_text())
    manifest = (REFUND / "manifest.json").read_bytes()
    baseline = analyse_continuity(
        loads(manifest.decode(), source="examples/continuity-refund/manifest.json"),
        provider,
        _bytes(provider),
        binding=binding,
        binding_source_bytes=_bytes(binding),
        as_of=AS_OF,
        mandate_bytes=manifest,
    )
    assert result["baseline"] == json.loads(baseline.to_result().to_json())
    assert baseline.outcomes[0].state == "reset"
    assert baseline.authority.as_dict()["breaches"] == []
    assert "continuity.state-reset" in {f.code for f in baseline.findings}
    assert result["findings"][-1]["code"] == "revision.continuation-unresolved"


@pytest.mark.parametrize("claim", ["comparison", "amendment"])
@pytest.mark.parametrize("state", ["unreviewed", "contested", "heuristic", "expired"])
def test_claim_reviews_are_independent(claim, state):
    raw = _raw()
    evidence = raw["controls"][0][claim]["evidence"]
    if state == "unreviewed":
        evidence.update(review=state, reviewer=None, expires=None)
    elif state == "contested":
        evidence["review"] = state
    elif state == "heuristic":
        evidence["confidence"] = state
    else:
        evidence["expires"] = "2026-10-09"
    result = _run(raw)
    row = result["assessments"][0]
    affected = "comparability" if claim == "comparison" else "issuer_amendment"
    other = "issuer_amendment" if claim == "comparison" else "comparability"
    assert row[affected] == "unresolved"
    assert row[other] != "unresolved"
    assert result["review_inputs_eligible"] is True
    assert f"revision.{claim}-untrusted" in {f["code"] for f in result["findings"]}


@pytest.mark.parametrize(
    ("relation", "expected"),
    [
        ("unknown", "unresolved"),
        ("incomparable", "not_comparable"),
    ],
)
def test_nonpositive_comparison_does_not_invent_equivalence(relation, expected):
    raw = _raw()
    raw["controls"][0]["comparison"]["relation"] = relation
    assert _run(raw)["assessments"][0]["comparability"] == expected


def test_unknown_amendment_and_late_decision_are_not_approval():
    raw = _raw()
    raw["controls"][0]["amendment"].update(
        status="unknown",
        issuer=None,
        decision_at=None,
        state_treatment="unknown",
    )
    raw["controls"][2]["amendment"]["decision_at"] = "2026-10-09T12:00:01Z"
    result = _run(raw)
    assert result["assessments"][0]["issuer_amendment"] == "unresolved"
    assert result["assessments"][1]["issuer_amendment"] == "unresolved"
    assert "revision.amendment-late" in {f["code"] for f in result["findings"]}
    raw["controls"][2]["amendment"]["decision_at"] = "2026-10-09T12:00:00Z"
    assert _run(raw)["assessments"][1]["issuer_amendment"] == "approved_retaining_state"


def test_approved_retention_never_excuses_a_reset():
    raw = _raw()
    raw["controls"][0]["amendment"].update(
        status="approved", decision_at="2026-10-09T11:00:00Z",
    )
    result = _run(raw)
    assert result["assessments"][0]["issuer_amendment"] == "approved_retaining_state"
    assert result["assessments"][0]["safe_continuation"] == "unresolved"
    baseline = result["baseline"]["outcomes"][0]
    assert baseline["state"] == "reset"
    assert baseline["issuer_amendment"] == "unresolved"


@pytest.mark.parametrize("relation", ["equivalent", "tightens"])
def test_numeric_widening_cannot_be_reviewed_as_equivalent_or_tightening(relation):
    raw, provider = _raw(), _raw("provider")
    provider["controls"][0]["provider_limits"] = [1000, 1200]
    raw["controls"][0]["comparison"]["relation"] = relation
    _pin(raw, provider)
    result = _run(raw, provider=provider)
    assert result["assessments"][0]["comparability"] == "unresolved"
    assert result["assessments"][0]["issuer_amendment"] == "not_required_within_reviewed_scope"
    assert "revision.comparison-inconsistent" in {f["code"] for f in result["findings"]}


@pytest.mark.parametrize("field", ["manifest_sha256", "provider_sha256", "binding_sha256"])
def test_each_input_digest_is_required(field):
    raw = _raw()
    raw[field] = "0" * 64
    result = _run(raw)
    assert result["review_inputs_eligible"] is False
    _assert_unresolved(result)


@pytest.mark.parametrize("side", ["review", "provider", "binding"])
@pytest.mark.parametrize("change", ["missing", "extra", "tampered"])
def test_each_source_namespace_fails_closed(side, change):
    artifact = {
        "review": RevisionReview.from_json(json.dumps(_raw())),
        "provider": AgentCoreContinuity.from_json(json.dumps(_raw("provider"))),
        "binding": ContinuityBinding.from_json((REFUND / "binding.json").read_text()),
    }[side]
    contents = _bytes(artifact)
    if change == "missing":
        contents.pop(next(iter(contents)))
    elif change == "extra":
        contents["extra"] = b"extra"
    else:
        contents[next(iter(contents))] += b" "
    result = _run(**{f"{side}_bytes": contents})
    assert result["review_inputs_eligible"] is False
    _assert_unresolved(result)


@pytest.mark.parametrize("side", ["provider", "binding"])
def test_baseline_acceptance_is_not_supplied_by_review(side):
    raw = _raw()
    value = (
        _raw("provider")
        if side == "provider"
        else json.loads((REFUND / "binding.json").read_text())
    )
    value["evidence"].update(review="unreviewed", reviewer=None, expires=None)
    reader = AgentCoreContinuity if side == "provider" else ContinuityBinding
    raw[f"{side}_sha256"] = _sha(reader.from_json(json.dumps(value)).to_json().encode())
    _assert_unresolved(_run(raw, **{side: value}))


@pytest.mark.parametrize(
    "change",
    ["transition", "revision", "limits", "same_mandate", "policy", "future", "before_binding"],
)
def test_control_joins_are_checked_without_rewriting_other_claims(change):
    raw, provider = _raw(), _raw("provider")
    row, control = raw["controls"][0], provider["controls"][0]
    if change == "transition":
        control["transition"] = "fresh_session"
    elif change == "revision":
        control["revision_changed"] = None
    elif change == "limits":
        control["provider_limits"] = [1000, 900, 700]
    elif change == "same_mandate":
        control["same_mandate"] = None
    elif change == "policy":
        row["policies"]["before"] = "tightened"
    elif change == "future":
        row["transition_at"] = "2026-10-11T00:00:00Z"
    else:
        row["transition_at"] = "2026-09-05T00:00:00Z"
    _pin(raw, provider)
    result = _run(raw, provider=provider)
    assert result["assessments"][0]["comparability"] == "unresolved"
    assert result["assessments"][0]["issuer_amendment"] == "unresolved"
    assert result["assessments"][0]["control_joined"] is False
    assert result["assessments"][1]["control_joined"] is True


def test_partial_review_does_not_drop_unreviewed_controls_and_unknown_control_blocks_all():
    raw = _raw()
    raw["controls"].pop()
    result = _run(raw)
    assert len(result["assessments"]) == 3
    assert result["assessments"][1]["comparability"] == "unresolved"
    assert "revision.review-missing" in {f["code"] for f in result["findings"]}
    raw["controls"][0]["id"] = "unknown"
    _assert_unresolved(_run(raw))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(revision_review_version=2),
        lambda r: r.update(revision_review_version=True),
        lambda r: r.update(extra=True),
        lambda r: r.pop("binding_sha256"),
        lambda r: r.update(provider_sha256="bad"),
        lambda r: r.update(controls=[]),
        lambda r: r["controls"].append(r["controls"][0]),
        lambda r: r["controls"][0].update(transition_at="2026-10-09"),
        lambda r: r["controls"][0].update(association=""),
        lambda r: r["controls"][0]["policies"].update(after="missing"),
        lambda r: r["controls"][0]["comparison"].update(relation="syntactically_equal"),
        lambda r: r["controls"][0]["comparison"].update(relation=[]),
        lambda r: r["controls"][0]["comparison"].update(scope=""),
        lambda r: r["controls"][0]["comparison"].update(sources=["missing"]),
        lambda r: r["controls"][0]["amendment"].update(status="waived"),
        lambda r: r["controls"][0]["amendment"].update(status="unknown"),
        lambda r: r["controls"][0]["amendment"].update(issuer=None),
        lambda r: r["controls"][0]["amendment"].update(state_treatment="reset"),
        lambda r: r["controls"][0]["amendment"].update(decision_at="2026-10-09T00:00:00Z"),
        lambda r: r["controls"][2]["amendment"].update(decision_at=None),
        lambda r: r["controls"][0]["comparison"]["evidence"].update(expires=None),
    ],
)
def test_strict_contract_rejects_ambiguous_claims(mutate):
    raw = _raw()
    mutate(raw)
    with pytest.raises(ContinuityFormatError):
        RevisionReview.from_json(json.dumps(raw))


def _args():
    args = ["continuity", "reconcile", "examples/continuity-refund/manifest.json"]
    for flag, artifact in [
        ("provider", EXAMPLE / "provider.json"),
        ("binding", REFUND / "binding.json"),
        ("review", EXAMPLE / "review.json"),
    ]:
        args.extend([f"--continuity-{flag}", str(artifact)])
        source_flag = "source" if flag == "provider" else f"{flag}-source"
        for source in json.loads(artifact.read_text())["sources"]:
            locator = source["locator"]
            args.extend([f"--continuity-{source_flag}", f"{locator}={ROOT / locator}"])
    args.extend(["--continuity-as-of", "2026-10-10T00:00:00Z"])
    return args


def test_cli_validates_and_preserves_global_unresolved_exit(capsys):
    assert main(["continuity", "validate", str(EXAMPLE / "review.json")]) == 0
    assert capsys.readouterr().out == "valid revision review v1\n"
    assert main([*_args(), "--json"]) == 1
    output = capsys.readouterr()
    assert not output.err
    actual = json.loads(output.out)
    expected = _run()
    assert actual == expected
    assert main(_args()) == 1
    output = capsys.readouterr()
    assert "BASELINE CONTINUITY (unchanged)" in output.out
    assert "safe continuation" in output.out
    assert not output.err


@pytest.mark.parametrize(
    "options",
    [
        ["--continuity-review", str(EXAMPLE / "provider.json")],
        ["--continuity-review", ""],
        ["--continuity-provider", str(EXAMPLE / "review.json")],
        ["--continuity-provider", str(ROOT / "examples/principal-continuity/profile.json")],
        ["--continuity-review-source", "extra=missing"],
        ["--ir"],
        ["--graph"],
    ],
)
def test_cli_refuses_wrong_roles_composition_and_extra_locators(options, capsys):
    assert main([*_args(), *options, "--json"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


@pytest.mark.parametrize("remove", ["review", "review-source", "binding"])
def test_cli_requires_review_source_pairs_and_a_binding(remove, capsys):
    args = _args()
    for flag in ["binding", "binding-source"] if remove == "binding" else [remove]:
        option = f"--continuity-{flag}"
        while option in args:
            i = args.index(option)
            del args[i : i + 2]
    assert main(args) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("name", "when"),
    [
        ("eligible", "2026-10-10T00:00:00Z"),
        ("expired", "2026-11-09T00:00:00Z"),
    ],
)
def test_fixed_result_fixtures(name, when, capsys):
    args = _args()
    args[-1] = when
    assert main([*args, "--json"]) == 1
    output = capsys.readouterr()
    assert not output.err
    assert (
        output.out.encode()
        == (ROOT / f"tests/fixtures/revision-review-result-v1-{name}.json").read_bytes()
    )


def test_review_canonicalization_and_expiry_boundary():
    raw = _raw()
    baseline = RevisionReview.from_json(json.dumps(raw)).to_json()
    raw["controls"].reverse()
    raw["sources"].reverse()
    assert RevisionReview.from_json(json.dumps(raw)).to_json() == baseline
    assert RevisionReview.from_json(baseline).to_json() == baseline
    result = _run(when=datetime(2026, 11, 8, 23, 59, 59, tzinfo=timezone.utc))
    assert result["assessments"][0]["comparability"] == "established_within_reviewed_scope"
