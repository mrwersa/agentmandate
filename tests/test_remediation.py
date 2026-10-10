import copy
import hashlib
import json
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import pytest

from agentmandate import Limits, Mandate, analyse, load
from agentmandate._remediation import _changed, plan
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]


def manifest(*, approved=False, budget=None, roles=None):
    return Mandate.parse(
        {
            "agent": "repair-example",
            "identity": "synthetic-caller",
            "limits": {"depth": 4, "effects": {} if budget is None else {"irreversible": budget}},
            "roles": {} if roles is None else roles,
            "tools": [
                {"name": "lookup", "effect": "read", "produces": "item"},
                {
                    "name": "delete",
                    "effect": "irreversible",
                    "requires": ["item"],
                    "requires_approval": approved,
                },
                {"name": "inspect", "effect": "read"},
            ],
        }
    )


def test_approval_ranks_before_removal_and_candidates_round_trip_without_mutation():
    original = manifest(roles={"operator": ["delete", "lookup"]})
    before = copy.deepcopy(original)
    result = plan(original, max_candidates=100)
    assert original == before
    assert result["baseline"] == analyse(original).as_dict()
    first = result["candidates"][0]
    assert first["edits"] == [{"tool": "delete", "kind": "require_approval"}]
    assert first["impact"]["lost_reachable_tools"] == []
    assert first["manifest"]["identity"] == original.identity
    assert first["manifest"]["limits"]["effects"] == {}
    removed = next(
        c
        for c in result["candidates"]
        if c["edits"]
        == [
            {"tool": "delete", "kind": "remove_tool"},
        ]
    )
    assert removed["impact"]["removed_role_members"] == {"operator": ["delete"]}
    assert removed["manifest"]["roles"] == {"operator": ["lookup"]}
    for candidate in result["candidates"]:
        restored = Mandate.parse(candidate["manifest"])
        assert (
            analyse(restored, depth=result["search"]["depth"]).as_dict() == (candidate["authority"])
        )
        assert not candidate["authority"]["breaches"]


def test_approval_cannot_repair_an_effect_budget_or_spending_breach():
    counted = plan(manifest(budget=1), max_candidates=100)
    assert counted["candidates"]
    assert all(any(e["kind"] == "remove_tool" for e in c["edits"]) for c in counted["candidates"])
    monetary = load(ROOT / "examples/dispute-resolver-v2.yaml")
    monetary = replace(
        monetary,
        tools=tuple(
            replace(t, requires_approval=False) if t.name == "issue_refund" else t
            for t in monetary.tools
        ),
    )
    result = plan(monetary, max_candidates=100)
    assert {b["kind"] for b in result["baseline"]["breaches"]} == {
        "ungated_effect",
        "cumulative_value",
    }
    assert all(
        c["edits"] != [{"tool": "issue_refund", "kind": "require_approval"}]
        for c in result["candidates"]
    )
    for c in result["candidates"]:
        assert c["manifest"]["limits"]["total"] == {"amount": "500", "currency": "GBP"}
        refund = Mandate.parse(c["manifest"]).tool("issue_refund")
        if refund is not None:
            assert refund.ceiling == monetary.tool("issue_refund").ceiling


def test_removing_the_only_producer_is_not_a_clean_repair():
    result = plan(manifest(), max_candidates=100)
    assert all(
        c["edits"] != [{"tool": "lookup", "kind": "remove_tool"}] for c in result["candidates"]
    )
    assert result["search"]["candidates_analyzed"] < result["search"]["combinations_examined"]
    assert _changed(manifest(), (("delete", "remove_tool"), ("delete", "require_approval"))) is None
    assert _changed(manifest(), tuple((n, "remove_tool") for n in manifest().tool_names)) is None


def test_keep_tools_checks_reachability_after_edits_not_just_tool_membership():
    source = load(ROOT / "examples/dispute-resolver-v2.yaml")
    result = plan(source, keep_tools=("issue_refund", "issue_refund"), max_candidates=100)
    assert result["keep_tools"] == ["issue_refund"]
    assert result["candidates"][0]["edits"] == [
        {"tool": "search_cases", "kind": "remove_tool"},
    ]
    assert all("issue_refund" in c["authority"]["reachable_tools"] for c in result["candidates"])
    assert plan(manifest(approved=True, budget=0), keep_tools=("delete",))["status"] == (
        "no_candidate_found_within_limits"
    )


@pytest.mark.parametrize("producer_effect,refund_effect", [
    ("read", "write"), ("read", "irreversible"), ("write", "irreversible"),
])
def test_tied_removals_prefer_losing_the_weaker_effect(producer_effect, refund_effect):
    source = load(ROOT / "examples/dispute-resolver-v2.yaml")
    source = replace(source, tools=tuple(
        replace(t, effect=producer_effect, requires_approval=True) if t.name == "search_cases"
        else replace(t, effect=refund_effect) if t.name == "issue_refund" else t
        for t in source.tools
    ))
    result = plan(source, max_edits=1, max_candidates=100)
    assert [c["edits"] for c in result["candidates"]] == [
        [{"tool": "search_cases", "kind": "remove_tool"}],
        [{"tool": "issue_refund", "kind": "remove_tool"}],
    ]
    assert [c["impact"]["lost_reachable_tools"] for c in result["candidates"]] == [
        ["search_cases"], ["issue_refund"],
    ]
    assert not result["candidates"][0]["authority"]["truncated"]
    assert all(not c["authority"]["breaches"] for c in result["candidates"])


def test_kept_consumer_cannot_be_stranded_behind_a_declared_producer_cycle():
    source = Mandate.parse({
        "agent": "producer-cycle",
        "tools": [
            {"name": "seed", "effect": "read", "produces": "item"},
            {"name": "loop", "effect": "read", "requires": ["item"], "produces": "item"},
            {"name": "delete", "effect": "irreversible", "requires": ["item"]},
        ],
    })
    unkept = plan(source, max_edits=1, max_candidates=100)
    stranded = next(c for c in unkept["candidates"] if c["edits"] == [
        {"tool": "seed", "kind": "remove_tool"},
    ])
    assert "delete" in {t["name"] for t in stranded["manifest"]["tools"]}
    assert "delete" not in stranded["authority"]["reachable_tools"]
    kept = plan(source, keep_tools=("delete",), max_edits=1, max_candidates=100)
    assert kept["candidates"]
    assert all("delete" in c["authority"]["reachable_tools"] for c in kept["candidates"])
    assert kept["candidates"][0]["edits"] == [{"tool": "delete", "kind": "require_approval"}]


@pytest.mark.parametrize("field", ["max_edits", "max_evaluations", "max_candidates"])
@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "2"])
def test_invalid_search_options_fail_before_analysis(field, bad):
    with pytest.raises(ValueError, match=f"{field} must"):
        plan(manifest(), **{field: bad})


@pytest.mark.parametrize("kept", [("absent",), (None,), ([],)])
def test_unknown_or_non_string_kept_tools_are_refused(kept):
    with pytest.raises(ValueError, match="name declared tools"):
        plan(manifest(), keep_tools=kept)


def test_known_but_unreachable_kept_tool_is_refused():
    source = manifest()
    source = replace(source, tools=tuple(t for t in source.tools if t.name != "lookup"))
    with pytest.raises(ValueError, match="reachable in the baseline"):
        plan(source, keep_tools=("delete",))


def test_missing_producer_input_requires_review_even_with_clean_reach():
    source = manifest()
    source = replace(source, tools=tuple(t for t in source.tools if t.name != "lookup"))
    result = plan(source)
    assert result["status"] == "input_requires_review"
    assert not result["baseline"]["breaches"]
    assert not result["candidates"]
    assert result["search"]["combinations_examined"] == 0
    assert result["search"]["enumeration_complete"] is None
    assert any(f["rule"] == "scope.missing-producer" for f in result["baseline_lint"])


def test_clean_baseline_and_empty_edit_domain_are_reported_without_a_repair_claim():
    clean = plan(manifest(approved=True))
    assert clean["status"] == "no_reachable_breach_within_bound" and not clean["candidates"]
    assert clean["search"]["enumeration_complete"] is None
    one = Mandate.parse(
        {
            "agent": "one",
            "limits": {"effects": {"write": 0}},
            "tools": [{"name": "write", "effect": "write"}],
        }
    )
    result = plan(one, keep_tools=("write",))
    assert result["search"]["enumeration_complete"]
    assert result["search"]["combinations_total"] == 0
    assert result["status"] == "no_candidate_found_within_limits"
    assert plan(one)["search"]["candidates_analyzed"] == 0  # Only edit makes tools empty.


def test_enumeration_and_reachability_cutoffs_are_separate():
    source = load(ROOT / "examples/dispute-resolver-v2.yaml")
    limited = plan(source, max_evaluations=1)
    assert limited["search"]["combinations_examined"] == 1
    assert not limited["search"]["enumeration_complete"]
    result = plan(source, max_candidates=1)
    assert result["search"]["enumeration_complete"]
    assert result["search"]["candidates_found"] > len(result["candidates"]) == 1
    assert not result["candidates"][0]["authority"]["truncated"]
    full = plan(source, max_candidates=100)
    assert any(c["authority"]["truncated"] for c in full["candidates"])
    shallow = plan(source, depth=1)
    assert shallow["baseline"]["depth"] == 1 and shallow["baseline"]["truncated"]
    assert shallow["status"] == "no_reachable_breach_within_bound"


@pytest.mark.parametrize("approved,budget", [(False, None), (False, 0), (False, 1), (True, 1)])
def test_small_graph_candidates_equal_independent_exhaustive_edit_oracle(approved, budget):
    source = manifest(approved=approved, budget=budget)
    actions = [(t.name, "remove_tool") for t in source.tools]
    if not approved:
        actions.append(("delete", "require_approval"))
    expected = set()
    for count in (1, 2):
        for edits in combinations(actions, count):
            removes = {n for n, k in edits if k == "remove_tool"}
            gates = {n for n, k in edits if k == "require_approval"}
            if removes & gates or len(removes) == len(source.tools):
                continue
            if "lookup" in removes and "delete" not in removes:
                continue
            tools = tuple(
                replace(t, requires_approval=True) if t.name in gates else t
                for t in source.tools
                if t.name not in removes
            )
            if not analyse(replace(source, tools=tools)).breaches:
                expected.add(frozenset(edits))
    result = plan(source, max_candidates=100, max_evaluations=100)
    assert result["search"]["enumeration_complete"]
    assert {
        frozenset((e["tool"], e["kind"]) for e in c["edits"]) for c in result["candidates"]
    } == expected


def test_remaining_lint_findings_are_not_hidden_by_a_reachability_repair():
    source = manifest()
    source = replace(source, tools=tuple(replace(t, principal="service") for t in source.tools))
    result = plan(source)
    assert not result["candidates"][0]["authority"]["breaches"]
    assert any(f["severity"] == "error" for f in result["candidates"][0]["lint"])


def test_two_independent_breaches_require_joint_edits_when_tools_are_kept():
    source = Mandate.parse(
        {
            "agent": "two",
            "tools": [
                {"name": "charge", "effect": "irreversible"},
                {"name": "delete", "effect": "irreversible"},
                {"name": "read", "effect": "read"},
            ],
        }
    )
    assert not plan(source, max_edits=1, keep_tools=("charge", "delete"))["candidates"]
    result = plan(source, max_edits=2, keep_tools=("charge", "delete"))
    assert result["candidates"][0]["edits"] == [
        {"tool": "charge", "kind": "require_approval"},
        {"tool": "delete", "kind": "require_approval"},
    ]
    assert len(result["baseline"]["breaches"]) == 2
    assert result["candidates"][0]["authority"]["reachable_tools"] == list(source.tool_names)


@pytest.mark.parametrize("graph", ["aws-iam-access-keys", "aws-postgres-mcp", "github-mcp-server"])
def test_real_graph_candidates_recheck_and_preserve_baseline(graph):
    source = load(ROOT / "docs/evidence" / graph / "mandate.yaml")
    # Explicit hypothetical budget on existing reviewed graph; not new observed mandate intent.
    source = replace(source, limits=Limits(depth=4, effects={"irreversible": 0}))
    result = plan(source, max_evaluations=64)
    assert result["baseline"] == analyse(source).as_dict()
    if graph == "aws-postgres-mcp":
        assert result["search"]["candidates_found"] == 7
        assert result["search"]["enumeration_complete"]
    elif graph == "github-mcp-server":
        assert result["status"] == "no_candidate_found_within_limits"
        assert not result["search"]["enumeration_complete"]
        assert result["search"]["combinations_examined"] == 64
    else:
        assert not result["baseline"]["breaches"] and not result["candidates"]
        assert result["baseline_lint"][0]["rule"] == "identity.service-principal"
    for candidate in result["candidates"]:
        assert analyse(Mandate.parse(candidate["manifest"])).as_dict() == candidate["authority"]
        assert candidate["manifest"]["limits"]["effects"] == {"irreversible": 0}
        assert not candidate["authority"]["breaches"]


@pytest.mark.parametrize("fixture", ["breached", "kept", "limited", "clean"])
def test_cli_result_baselines(fixture, capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    case = json.loads((ROOT / f"tests/fixtures/remediation-{fixture}-v1.json").read_text())
    before = (ROOT / case["argv"][1]).read_bytes()
    assert main(case["argv"]) == case["exit"]
    captured = capsys.readouterr()
    assert json.loads(captured.out) == case["result"]
    assert not captured.err
    assert before == (ROOT / case["argv"][1]).read_bytes()
    assert case["result"]["input"]["manifest_sha256"] == hashlib.sha256(before).hexdigest()


def test_cli_text_keeps_original_breach_and_scope(capsys):
    assert main(["remediate", str(ROOT / "examples/dispute-resolver-v2.yaml")]) == 1
    output = capsys.readouterr().out
    assert "BREACH cumulative_value" in output
    assert "candidates require human selection" in output
    assert "no_reachable_breach_within_bound" in output
    assert "truncated=True" in output and "enumeration_complete=True" in output


def test_cli_missing_producer_is_a_finding_and_clean_text_exit_is_zero(tmp_path, capsys):
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps(
            {
                "agent": "dangling",
                "tools": [
                    {"name": "read", "effect": "read", "requires": ["missing"]},
                ],
            }
        )
    )
    assert main(["remediate", str(path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "input_requires_review"
    assert main(["remediate", str(ROOT / "probes/search/pure-read.json")]) == 0
    assert "STATUS no_reachable_breach_within_bound" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["missing", "malformed", "utf8", "keep", "unreachable"])
def test_cli_usage_errors_leave_stdout_empty(bad, tmp_path, capsys):
    path = tmp_path / "input.json"
    args = ["remediate", str(path), "--json"]
    if bad == "malformed":
        path.write_text("{broken")
    elif bad == "utf8":
        path.write_bytes(b"\xff")
    elif bad in {"keep", "unreachable"}:
        path.write_text(
            json.dumps(
                {
                    "agent": "x",
                    "tools": [
                        {"name": "read", "effect": "read", "requires": ["missing"]},
                    ],
                }
            )
        )
        args.extend(["--keep-tool", "absent" if bad == "keep" else "read"])
    assert main(args) == 2
    output = capsys.readouterr()
    assert not output.out and output.err.startswith("error: ")


@pytest.mark.parametrize(
    "flag",
    [
        "--depth",
        "--max-edits",
        "--max-evaluations",
        "--max-candidates",
    ],
)
def test_cli_non_positive_limits_are_usage_errors(flag, capsys):
    with pytest.raises(SystemExit) as error:
        main(["remediate", "unused", flag, "0"])
    assert error.value.code == 2
    assert not capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--condition", "--ir", "--apply"])
def test_unsupported_composition_is_refused_before_input_read(flag, capsys):
    with pytest.raises(SystemExit) as error:
        main(["remediate", "missing-input", flag, "unsupported-input"])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out and "unrecognized arguments" in output.err
