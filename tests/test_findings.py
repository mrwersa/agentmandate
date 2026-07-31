from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmandate import analyse, load, loads
from agentmandate.findings import render_sarif, to_mermaid, to_sarif

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
V1 = EXAMPLES / "dispute-resolver.yaml"
V2 = EXAMPLES / "dispute-resolver-v2.yaml"
SOD = EXAMPLES / "dispute-resolver-sod.yaml"


def breaching():
    mandate = load(V2)
    return analyse(mandate), mandate


def clean():
    mandate = load(V1)
    return analyse(mandate), mandate


def test_sarif_is_a_well_formed_log() -> None:
    authority, _ = breaching()

    log = to_sarif(authority, V2, tool_version="1.2.3")

    assert log["version"] == "2.1.0"
    assert log["$schema"].endswith("sarif-schema-2.1.0.json")
    driver = log["runs"][0]["tool"]["driver"]
    assert driver["name"] == "AgentMandate"
    assert driver["version"] == "1.2.3"
    assert log["runs"][0]["results"]


def test_every_result_declares_a_rule_that_exists() -> None:
    authority, _ = breaching()

    log = to_sarif(authority, V2)
    declared = {rule["id"] for rule in log["runs"][0]["tool"]["driver"]["rules"]}

    # A result citing a rule the driver never declared is the most common way
    # a SARIF upload is rejected.
    assert declared
    assert all(r["ruleId"] in declared for r in log["runs"][0]["results"])


def test_findings_are_errors_not_warnings() -> None:
    # These already exit non-zero. Downgrading them in the UI would say
    # something different from the exit code, and the two disagreeing is how a
    # gate stops being believed.
    authority, _ = breaching()

    log = to_sarif(authority, V2)

    assert all(r["level"] == "error" for r in log["runs"][0]["results"])
    assert all(
        rule["defaultConfiguration"]["level"] == "error"
        for rule in log["runs"][0]["tool"]["driver"]["rules"]
    )


def test_a_result_is_anchored_at_the_last_tool_on_the_path() -> None:
    authority, _ = breaching()

    result = to_sarif(authority, V2)["runs"][0]["results"][0]
    region = result["locations"][0]["physicalLocation"]["region"]
    text = V2.read_text(encoding="utf-8").splitlines()[region["startLine"] - 1]

    assert "issue_refund" in text
    # And the message admits the anchor is a convention, because a compound
    # breach has no single guilty line.
    assert "rather than at a guilty line" in result["message"]["text"]
    assert "Reachable path:" in result["message"]["text"]


def test_the_fingerprint_survives_the_manifest_being_reformatted() -> None:
    authority, _ = breaching()
    original = to_sarif(authority, V2)["runs"][0]["results"][0]

    # Same authority, different file layout. GitHub must not call this new.
    moved = loads("\n\n" + V2.read_text(encoding="utf-8"))
    shifted = to_sarif(analyse(moved), V2)["runs"][0]["results"][0]

    assert original["partialFingerprints"] == shifted["partialFingerprints"]


def test_a_clean_manifest_produces_a_log_with_no_results() -> None:
    authority, _ = clean()

    log = to_sarif(authority, V1)

    assert log["runs"][0]["results"] == []
    assert log["runs"][0]["tool"]["driver"]["rules"] == []


def test_an_unreadable_manifest_still_produces_a_log() -> None:
    # Line anchoring is a nicety. Losing it must not lose the finding.
    authority, _ = breaching()

    log = to_sarif(authority, Path("no-such-file.yaml"))
    region = log["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]

    assert region["startLine"] == 1


def test_an_unknown_breach_kind_still_gets_a_rule() -> None:
    authority, _ = analyse(load(SOD)), load(SOD)

    log = to_sarif(authority, SOD)
    ids = {rule["id"] for rule in log["runs"][0]["tool"]["driver"]["rules"]}

    assert ids == {r["ruleId"] for r in log["runs"][0]["results"]}


def test_render_sarif_emits_parseable_json() -> None:
    authority, _ = breaching()

    payload = json.loads(render_sarif(authority, V2, "9.9.9"))

    assert payload["runs"][0]["tool"]["driver"]["version"] == "9.9.9"


def test_the_graph_shows_one_node_per_step_with_its_binding() -> None:
    # One node per tool produced self-loops, because the whole point of a
    # compound breach is often the same tool called twice on different
    # bindings, which a node per tool cannot show.
    authority, mandate = breaching()

    diagram = to_mermaid(authority, mandate)

    assert diagram.startswith("flowchart LR")
    assert "case#1" in diagram and "case#2" in diagram
    assert "s0 --> s1" in diagram
    assert "--> breach" in diagram
    assert not any(
        f"s{i} --> s{i}" in diagram for i in range(len(authority.breaches[0].path))
    )


def test_the_graph_shape_comes_from_the_declared_effect() -> None:
    # `Authority.effects` is (effect class, scope) pairs, not a per-tool map.
    # Reading it as one drew every node the same and said nothing.
    authority, mandate = breaching()

    diagram = to_mermaid(authority, mandate)

    assert '(["search_cases' in diagram      # read: rounded
    assert '["issue_refund' in diagram       # irreversible: box


def test_the_graph_names_what_is_reachable_but_not_on_the_path() -> None:
    authority, mandate = breaching()

    assert "also reachable:" in to_mermaid(authority, mandate)


def test_a_clean_manifest_draws_the_reachable_tools_and_says_so() -> None:
    authority, mandate = clean()

    diagram = to_mermaid(authority, mandate)

    assert "no reachable breach within depth" in diagram
    assert "class ok ok;" in diagram
    assert "--> breach" not in diagram


def test_the_graph_reports_further_breaches_rather_than_drawing_them_all() -> None:
    authority, mandate = analyse(load(SOD)), load(SOD)

    diagram = to_mermaid(authority, mandate)

    if len(authority.breaches) > 1:
        assert "further reachable breach" in diagram
    if authority.ungated_irreversible:
        assert "ungated irreversible:" in diagram


def test_more_than_one_breach_is_summarised_rather_than_drawn() -> None:
    # Drawing every path turns the diagram into the path listing it replaces.
    # Confirm the summary line rather than assuming a fixture has two.
    mandate = loads(
        """
        version: 1
        agent: multi
        limits:
          total: { amount: 100, currency: GBP }
          depth: 6
        tools:
          - name: seed
            effect: read
            produces: case
            unbounded: true
          - name: pay
            effect: irreversible
            requires: [case]
            value_arg: amount
            scope_key: case
            ceiling: { amount: 100, currency: GBP }
          - name: wipe
            effect: irreversible
            requires: [case]
        """
    )
    authority = analyse(mandate)

    assert len(authority.breaches) > 1
    assert "further reachable breach" in to_mermaid(authority, mandate)


def test_a_hostile_tool_name_cannot_inject_graph_syntax() -> None:
    # Tool names reach here from `mandate scan`, which exists to read
    # untrusted MCP catalogues. scan.py already quotes them when writing YAML
    # for exactly this reason; a Mermaid label is the same exposure.
    mandate = loads(
        """
        version: 1
        agent: victim
        limits: { total: { amount: 100, currency: GBP }, depth: 6 }
        tools:
          - { name: 'seed"] --> evil["OWNED', effect: read, produces: case,
              unbounded: true }
          - { name: pay, effect: irreversible, requires: [case],
              value_arg: amount, scope_key: case,
              ceiling: { amount: 100, currency: GBP } }
        """
    )

    diagram = to_mermaid(analyse(mandate), mandate)

    assert "--> evil" not in diagram
    assert "#quot;" in diagram
    # One edge per consecutive pair of steps, and nothing the name smuggled in.
    assert diagram.count("-->") == len(analyse(mandate).breaches[0].path)


def test_the_breach_detail_is_escaped_too() -> None:
    mandate = loads(
        """
        version: 1
        agent: victim
        limits: { total: { amount: 10, currency: GBP }, depth: 4 }
        tools:
          - { name: 'a"]-->x[', effect: read, produces: case, unbounded: true }
          - { name: 'b"]-->y[', effect: irreversible, requires: [case],
              value_arg: amount, scope_key: case,
              ceiling: { amount: 10, currency: GBP } }
        """
    )

    diagram = to_mermaid(analyse(mandate), mandate)

    assert "-->x[" not in diagram
    assert "-->y[" not in diagram


def test_a_json_manifest_anchors_at_the_right_line(tmp_path: Path) -> None:
    # The docstring claimed JSON worked. It did not: every result fell back to
    # line 1, which puts the annotation on the wrong part of the file.
    import json as json_module

    import yaml

    payload = yaml.safe_load(V2.read_text(encoding="utf-8"))
    path = tmp_path / "mandate.json"
    path.write_text(json_module.dumps(payload, indent=2), encoding="utf-8")

    authority = analyse(load(path))
    region = to_sarif(authority, path)["runs"][0]["results"][0]["locations"][0][
        "physicalLocation"
    ]["region"]
    line = path.read_text(encoding="utf-8").splitlines()[region["startLine"] - 1]

    assert "issue_refund" in line


def test_a_manifest_inside_the_working_directory_gets_a_relative_uri() -> None:
    # Code scanning resolves the uri against the repository root, so an
    # absolute path attaches the finding to nothing.
    authority = analyse(load(V2))

    uri = to_sarif(authority, V2)["runs"][0]["results"][0]["locations"][0][
        "physicalLocation"
    ]["artifactLocation"]["uri"]

    assert not uri.startswith("/")
    assert uri.endswith("examples/dispute-resolver-v2.yaml")


def test_a_manifest_outside_the_working_directory_keeps_its_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mandate.yaml"
    path.write_text(V2.read_text(encoding="utf-8"), encoding="utf-8")

    uri = to_sarif(analyse(load(path)), path)["runs"][0]["results"][0]["locations"][0][
        "physicalLocation"
    ]["artifactLocation"]["uri"]

    assert uri == path.as_posix()


@pytest.mark.parametrize("style", ["block", "flow", "json"])
def test_every_manifest_spelling_anchors_at_the_tool(
    tmp_path: Path, style: str
) -> None:
    # Flow style was missed at first and every result anchored at line 1,
    # which is not a missing answer but a wrong one: line 1 is `version:`, so
    # the annotation landed somewhere unrelated to the finding.
    import json as json_module

    import yaml

    data = yaml.safe_load(V2.read_text(encoding="utf-8"))
    if style == "block":
        text = V2.read_text(encoding="utf-8")
        suffix = "yaml"
    elif style == "json":
        text = json_module.dumps(data, indent=2)
        suffix = "json"
    else:
        rows = "".join(
            "  - { "
            + ", ".join(
                f"{k}: {json_module.dumps(v) if isinstance(v, (dict, list)) else v}"
                for k, v in tool.items()
            )
            + " }\n"
            for tool in data["tools"]
        )
        text = (
            "version: 1\nagent: dispute-resolver\n"
            "limits: { total: { amount: 500, currency: GBP }, depth: 8 }\n"
            f"tools:\n{rows}"
        )
        suffix = "yaml"

    path = tmp_path / f"mandate.{suffix}"
    path.write_text(text, encoding="utf-8")

    region = to_sarif(analyse(load(path)), path)["runs"][0]["results"][0][
        "locations"
    ][0]["physicalLocation"]["region"]
    line = path.read_text(encoding="utf-8").splitlines()[region["startLine"] - 1]

    assert "issue_refund" in line
