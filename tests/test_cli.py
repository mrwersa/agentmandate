import hashlib
import json
from pathlib import Path

import pytest

from agentmandate import __version__
from agentmandate._continuity import ContinuityResult
from agentmandate.cli import EXIT_FINDING, EXIT_OK, EXIT_USAGE, main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
V1 = str(EXAMPLES / "dispute-resolver.yaml")
V2 = str(EXAMPLES / "dispute-resolver-v2.yaml")
SOD = str(EXAMPLES / "dispute-resolver-sod.yaml")
TRACES = str(EXAMPLES / "observed-calls.jsonl")
ROOT = EXAMPLES.parent
AGENTKIT_INVENTORY = ROOT / "tests/fixtures/dynamic-inventory-agentkit-v1.json"
SENTRY_INVENTORY = ROOT / "tests/fixtures/dynamic-inventory-sentry-v1.json"
CONDITION = ROOT / "tests/fixtures/condition-statement-v1.json"
CONTEXT = ROOT / "tests/fixtures/condition-context-select-v1.json"
CONTEXT_COMPLETE = ROOT / "tests/fixtures/condition-context-select-only-complete-v1.json"
CONDITION_CAPTURE = ROOT / "tests/fixtures/condition-context-capture.sql"
CONDITIONAL_MANIFEST_PATH = ROOT / "tests/fixtures/conditional-mandate-v1.yaml"
CONDITIONAL_SOURCE = ROOT / "tests/fixtures/conditional-source"
CONDITIONAL_REACH_RESULT = ROOT / "tests/fixtures/conditional-reach-result-v1.json"
CONDITIONAL_DRIFT_RESULT = ROOT / "tests/fixtures/conditional-drift-result-v1.json"
DELEGATION_ATTACHMENT = ROOT / "tests/fixtures/delegation-attachment-v2.json"
DELEGATION_CHAIN = ROOT / "tests/fixtures/delegation-chain-authorizer-v1.json"
DELEGATION_CAPTURE = ROOT / "docs/evidence/authorizer-delegation/capture.json"
CEDAR_EVIDENCE = ROOT / "docs/evidence/agentcore-refund-policy"
CEDAR_MANIFEST = CEDAR_EVIDENCE / "mandate.yaml"
CEDAR_BASELINE = CEDAR_EVIDENCE / "managed-oracle-v1.json"
CEDAR_CANDIDATE = CEDAR_EVIDENCE / "candidate-managed-oracle-v1.json"
CEDAR_DIFF_RESULT = ROOT / "tests/fixtures/cedar-effective-diff-v1.json"
PRODUCER_FIXTURE = ROOT / "tests/fixtures/producer-accepted-synthetic"
PRODUCER_BOUNDARY = PRODUCER_FIXTURE / "boundary.json"
PRODUCER_MANIFEST = PRODUCER_FIXTURE / "manifest.json"
PRODUCER_MANIFEST_INPUT = str(PRODUCER_MANIFEST.relative_to(ROOT))
PRODUCER_SELECTION = PRODUCER_FIXTURE / "selection.json"
PRODUCER_RESULT = ROOT / "tests/fixtures/producer-reach-result-v1.json"
CONTINUITY_FIXTURE = ROOT / "tests/fixtures/continuity-accepted-synthetic"
CONTINUITY_MANIFEST = CONTINUITY_FIXTURE / "manifest.json"
CONTINUITY_PROVIDER = CONTINUITY_FIXTURE / "provider.json"
CONTINUITY_BINDING = CONTINUITY_FIXTURE / "binding.json"

CONDITIONAL_MANIFEST = """
agent: sql-agent
tools:
  - name: run_query
    effect: irreversible
    produces: rows
"""


def condition_args(context: Path = CONTEXT_COMPLETE, *, as_of: str = "2027-01-01"):
    return [
        "--condition",
        str(CONDITION),
        "--condition-context",
        str(context),
        "--condition-capture",
        str(CONDITION_CAPTURE),
        "--condition-as-of",
        as_of,
    ]


def write_conditional_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "mandate.yaml"
    path.write_text(CONDITIONAL_MANIFEST, encoding="utf-8")
    return path


def write_conditional_source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    module = root / "src/postgres-server/server.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from strands import Agent, tool\n\n"
        "@tool\n"
        "def run_query(sql: str) -> str:\n"
        "    return sql\n\n"
        "run_query = Agent(tools=[run_query])\n",
        encoding="utf-8",
    )
    return root


def delegation_args(*, as_of: str = "2026-08-25T12:00:00Z") -> list[str]:
    return [
        "--delegation-attachment",
        str(DELEGATION_ATTACHMENT),
        "--delegation-chain",
        str(DELEGATION_CHAIN),
        "--delegation-capture",
        f"docs/evidence/authorizer-delegation/capture.json={DELEGATION_CAPTURE}",
        "--delegation-as-of",
        as_of,
        "--delegation-target-source",
        "deploy/agent.py",
        "--delegation-target-binding",
        "agent",
    ]


def continuity_args(*, binding: bool = True) -> list[str]:
    arguments = [
        "--continuity-provider",
        str(CONTINUITY_PROVIDER),
        "--continuity-source",
        "tests/fixtures/continuity-accepted-synthetic/provider-control.json="
        + str(CONTINUITY_FIXTURE / "provider-control.json"),
        "--continuity-as-of",
        "2026-09-03T12:00:00Z",
    ]
    if binding:
        arguments.extend(
            [
                "--continuity-binding",
                str(CONTINUITY_BINDING),
                "--continuity-binding-source",
                "tests/fixtures/continuity-accepted-synthetic/binding-verification.json="
                + str(CONTINUITY_FIXTURE / "binding-verification.json"),
                "--continuity-binding-source",
                "tests/fixtures/continuity-accepted-synthetic/policy.json="
                + str(CONTINUITY_FIXTURE / "policy.json"),
            ]
        )
    return arguments


def producer_args(*, as_of: str = "2026-09-03") -> list[str]:
    args = [
        "--producer-boundary",
        str(PRODUCER_BOUNDARY),
    ]
    for name in ("catalogue.json", "outcomes.json", "adapter.py"):
        path = PRODUCER_FIXTURE / name
        args.extend(
            [
                "--producer-source",
                f"tests/fixtures/producer-accepted-synthetic/{name}={path}",
            ]
        )
    args.extend(
        [
            "--producer-selection",
            PRODUCER_SELECTION.read_text(encoding="utf-8"),
            "--producer-as-of",
            as_of,
        ]
    )
    return args


def write_delegation_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "mandate.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "agent": "export-agent",
                "tools": [
                    {
                        "name": "export_records",
                        "effect": "read",
                        "requires": ["openid"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def write_analyzable_delegation_chain(tmp_path: Path) -> Path:
    raw = json.loads(DELEGATION_CHAIN.read_text(encoding="utf-8"))
    for hop in raw["hops"]:
        hop["validity"] = {
            "kind": "window",
            "issued_at": "2026-08-25T00:00:00Z",
            "expires_at": "2026-08-26T00:00:00Z",
        }
        for dimension, members in {
            "tools": ["export_records"],
            "effects": ["read"],
        }.items():
            hop["surface"][dimension].update(
                domain="demo",
                basis="deployment_policy",
                completeness="complete",
                members=members,
                evidence=hop["evidence"],
                source=hop["source"],
            )
    path = tmp_path / "chain.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_lint_is_clean_on_the_shipped_v1_example(capsys):
    assert main(["lint", V1]) == EXIT_OK
    assert "no single-manifest findings" in capsys.readouterr().out


def test_lint_reports_findings_and_exits_non_zero(capsys):
    assert main(["lint", SOD]) == EXIT_FINDING
    assert "sod.single-identity" in capsys.readouterr().out


def test_reach_finds_no_breach_in_v1(capsys):
    assert main(["reach", V1]) == EXIT_OK
    out = capsys.readouterr().out
    assert "no reachable breach" in out
    assert "most extractable 500 GBP" in out


def test_reach_finds_the_compound_breach_in_v2(capsys):
    """The example that motivates the package must keep working."""
    assert main(["reach", V2]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "BREACH" in out
    assert "exceeds limit 500 GBP" in out
    assert "issue_refund" in out


def test_reach_reports_truncation_at_a_shallow_depth(capsys):
    assert main(["reach", V2, "--depth", "2"]) == EXIT_OK
    assert "search truncated" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("flag", "path", "output"),
    [
        ("--condition", CONDITION, "valid tool condition v1"),
        ("--context", CONTEXT_COMPLETE, "valid condition context v1"),
    ],
)
def test_conditions_validate_is_structural_only(flag, path, output, capsys):
    assert main(["conditions", "validate", flag, str(path)]) == EXIT_OK
    assert capsys.readouterr().out == f"{output}\n"


def test_conditions_validate_failure_emits_no_stdout(tmp_path, capsys):
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"condition_version":1,"unexpected":true}', encoding="utf-8")

    assert main(["conditions", "validate", "--condition", str(invalid)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


@pytest.mark.parametrize(
    ("flag", "path", "output"),
    [
        ("--attachment", DELEGATION_ATTACHMENT, "valid delegation attachment v2"),
        ("--chain", DELEGATION_CHAIN, "valid delegation chain v1"),
    ],
)
def test_delegations_validate_is_structural_only(flag, path, output, capsys):
    assert main(["delegations", "validate", flag, str(path)]) == EXIT_OK
    assert capsys.readouterr().out == f"{output}\n"


def test_delegations_validate_failure_emits_no_stdout(tmp_path, capsys):
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"delegation_version":1,"unexpected":true}', encoding="utf-8")

    assert main(["delegations", "validate", "--chain", str(invalid)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def cedar_align_args(oracle: Path = CEDAR_BASELINE) -> list[str]:
    return [
        "cedar",
        "align",
        str(CEDAR_MANIFEST),
        "--oracle",
        str(oracle),
        "--source-root",
        str(CEDAR_EVIDENCE),
        "--as-of",
        "2026-08-29",
    ]


def cedar_diff_args() -> list[str]:
    return [
        "cedar",
        "diff",
        str(CEDAR_MANIFEST),
        "--baseline-oracle",
        str(CEDAR_BASELINE),
        "--baseline-root",
        str(CEDAR_EVIDENCE),
        "--candidate-oracle",
        str(CEDAR_CANDIDATE),
        "--candidate-root",
        str(CEDAR_EVIDENCE),
        "--as-of",
        "2026-08-29",
    ]


def test_cedar_validate_is_structural_only(capsys) -> None:
    assert main(["cedar", "validate", str(CEDAR_BASELINE)]) == EXIT_OK
    assert capsys.readouterr().out == "valid managed Cedar oracle v1\n"


def test_cedar_align_renders_exact_managed_narrowing(capsys) -> None:
    assert main(cedar_align_args()) == EXIT_FINDING
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "managed Cedar  evaluated as of 2026-08-29" in captured.out
    assert "ALIGNED    process_refund (allow-under-limit)" in captured.out
    assert "NARROWS    process_refund (deny-over-limit)" in captured.out


def test_cedar_align_candidate_json_is_clean_and_versioned(capsys) -> None:
    assert main([*cedar_align_args(CEDAR_CANDIDATE), "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == "agentmandate.cedar-alignment/v1"
    assert payload["clean"] is True
    assert len(payload["inputs"]["manifest_sha256"]) == 64
    assert set(payload["inputs"]["oracle"]) == {
        "oracle_sha256",
        "profile_sha256",
        "mapping_sha256",
        "source_sha256",
    }
    assert all(
        len(payload["inputs"]["oracle"][key]) == 64
        for key in ("oracle_sha256", "profile_sha256", "mapping_sha256")
    )
    assert all(
        len(value) == 64
        for value in payload["inputs"]["oracle"]["source_sha256"].values()
    )
    assert {item["alignment"] for item in payload["alignments"]} == {"aligned_allow"}


def test_cedar_diff_emits_the_live_widening_before_finding_exit(capsys) -> None:
    assert main([*cedar_diff_args(), "--json"]) == EXIT_FINDING
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)

    assert payload["schema"] == "agentmandate.cedar-effective-diff/v1"
    assert [item["classification"] for item in payload["changes"]] == [
        "stable_allow",
        "widens",
    ]
    assert payload["findings"] == []
    assert payload["clean"] is False
    assert set(payload["inputs"]) == {
        "manifest_sha256",
        "baseline",
        "candidate",
    }
    assert set(payload["inputs"]["baseline"]) == {
        "oracle_sha256",
        "profile_sha256",
        "mapping_sha256",
        "source_sha256",
    }

    assert main(cedar_diff_args()) == EXIT_FINDING
    text = capsys.readouterr().out
    assert "STABLE_ALLOW process_refund: allow -> allow" in text
    assert "WIDENS       process_refund: deny -> allow" in text


def test_cedar_diff_public_json_fixture_is_byte_stable(capsys) -> None:
    assert main([*cedar_diff_args(), "--json"]) == EXIT_FINDING
    assert capsys.readouterr().out == CEDAR_DIFF_RESULT.read_text(encoding="utf-8")


@pytest.mark.parametrize("as_of", ["20260829", "2026-99-29"])
def test_cedar_rejects_noncanonical_dates_before_output(as_of, capsys) -> None:
    args = cedar_align_args()
    args[args.index("--as-of") + 1] = as_of

    assert main(args) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--as-of must be YYYY-MM-DD" in captured.err


def test_cedar_tampering_emits_a_complete_unresolved_result(tmp_path, capsys) -> None:
    raw = json.loads(CEDAR_BASELINE.read_text(encoding="utf-8"))
    for source in raw["sources"]:
        content = (CEDAR_EVIDENCE / source["locator"]).read_bytes()
        (tmp_path / source["locator"]).write_bytes(content)
    (tmp_path / "deny-response.json").write_text("tampered", encoding="utf-8")
    args = cedar_align_args()
    args[args.index("--source-root") + 1] = str(tmp_path)

    assert main(args) == EXIT_FINDING
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "UNRESOLVED" in captured.out
    assert "managed.source-untrusted" in captured.out
    assert "digest does not match locator 'deny-response.json'" in captured.out


def test_cedar_missing_sources_and_malformed_oracles_emit_no_output(tmp_path, capsys) -> None:
    args = cedar_align_args()
    args[args.index("--source-root") + 1] = str(tmp_path)
    assert main(args) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    assert main(["cedar", "validate", str(invalid)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "missing field" in captured.err


def test_cedar_source_root_rejects_files_and_escaping_symlinks(tmp_path, capsys) -> None:
    args = cedar_align_args()
    args[args.index("--source-root") + 1] = str(CEDAR_BASELINE)
    assert main(args) == EXIT_USAGE
    assert "source root must be a directory" in capsys.readouterr().err

    raw = json.loads(CEDAR_BASELINE.read_text(encoding="utf-8"))
    for source in raw["sources"]:
        target = CEDAR_EVIDENCE / source["locator"]
        (tmp_path / source["locator"]).symlink_to(target)
    args[args.index("--source-root") + 1] = str(tmp_path)
    assert main(args) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "outside the source root" in captured.err


def test_cedar_diff_renders_comparison_findings(capsys) -> None:
    args = cedar_diff_args()
    args[args.index("--as-of") + 1] = "2027-08-30"

    assert main(args) == EXIT_FINDING
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "FINDING       managed.comparison-untrusted" in captured.out


def test_reach_renders_authorizer_delegation_uncertainty(capsys, tmp_path):
    manifest = write_delegation_manifest(tmp_path)

    assert main(["reach", str(manifest), *delegation_args()]) == EXIT_FINDING
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "delegations  evaluated as of 2026-08-25T12:00:00Z" in captured.out
    assert "UNRESOLVED" in captured.out
    assert "hop validity lacks an absolute timestamp window" in captured.out
    assert "WIDENS" not in captured.out


def test_reach_delegation_json_is_namespaced_and_complete(capsys, tmp_path):
    manifest = write_delegation_manifest(tmp_path)

    assert main(["reach", str(manifest), *delegation_args(), "--json"]) == EXIT_FINDING
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    delegation = payload["delegations"]
    assert delegation["schema"] == "agentmandate.delegations/v1"
    assert delegation["as_of"] == "2026-08-25T12:00:00Z"
    assert delegation["attenuated"] == []
    assert {item["code"] for item in delegation["findings"]} == {
        "delegation.surface-unresolved",
        "delegation.validity-unresolved",
    }
    assert all(item["support"] for item in delegation["findings"])
    assert hashlib.sha256(captured.out.encode()).hexdigest() == (
        "37e8cc7f786e4e6b0bff38325d0770d72a888c6059eee82d71c62fba8ed2492d"
    )


def test_reach_renders_clean_delegation_attenuation(capsys, tmp_path):
    manifest = write_delegation_manifest(tmp_path)
    chain = write_analyzable_delegation_chain(tmp_path)
    args = delegation_args(as_of="2026-08-25T00:00:00Z")
    args[args.index("--delegation-chain") + 1] = str(chain)

    assert main(["reach", str(manifest), *args]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "ATTENUATED" in captured.out
    assert "UNRESOLVED" not in captured.out and "WIDENS" not in captured.out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--delegation-attachment", str(DELEGATION_ATTACHMENT)], "chain is required"),
        (["--delegation-chain", str(DELEGATION_CHAIN)], "attachment is required"),
        (
            delegation_args(as_of="2026-08-25T12:00:00+00:00"),
            "canonical UTC timestamp",
        ),
        (
            [*delegation_args()[:4], *delegation_args()[6:]],
            "capture is required",
        ),
        (
            [*delegation_args(), "--delegation-capture", "bad"],
            "LOCATOR=PATH",
        ),
    ],
)
def test_reach_delegation_input_failures_emit_no_stdout(args, message, capsys, tmp_path):
    manifest = write_delegation_manifest(tmp_path)

    assert main(["reach", str(manifest), *args]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_reach_delegation_requires_every_context_field(capsys, tmp_path):
    manifest = write_delegation_manifest(tmp_path)
    complete = delegation_args()
    for flag, message in [
        ("--delegation-as-of", "as-of is required"),
        ("--delegation-target-source", "target-source is required"),
        ("--delegation-target-binding", "target-binding is required"),
    ]:
        index = complete.index(flag)
        args = [*complete[:index], *complete[index + 2 :]]
        assert main(["reach", str(manifest), *args]) == EXIT_USAGE
        captured = capsys.readouterr()
        assert captured.out == "" and message in captured.err


def test_reach_delegation_rejects_bad_capture_mappings(capsys, tmp_path):
    manifest = write_delegation_manifest(tmp_path)
    capture = tmp_path / "other.json"
    capture.write_text("{}", encoding="utf-8")
    cases = [
        ("=missing", "LOCATOR=PATH"),
        (f"undeclared={capture}", "undeclared locator"),
    ]
    for value, message in cases:
        args = [*delegation_args(), "--delegation-capture", value]
        assert main(["reach", str(manifest), *args]) == EXIT_USAGE
        captured = capsys.readouterr()
        assert captured.out == "" and message in captured.err

    locator = "docs/evidence/authorizer-delegation/capture.json"
    args = [*delegation_args(), "--delegation-capture", f"{locator}={capture}"]
    assert main(["reach", str(manifest), *args]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == "" and "different capture bytes" in captured.err


@pytest.mark.parametrize("format_flag", ["--sarif", "--graph"])
def test_reach_refuses_delegation_formats_before_output(format_flag, capsys, tmp_path):
    manifest = write_delegation_manifest(tmp_path)

    assert main(["reach", str(manifest), *delegation_args(), format_flag]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "human or --json" in captured.err


def test_reach_refuses_delegation_ir_and_condition_composition(capsys):
    assert (
        main(
            [
                "reach",
                "--ir",
                str(ROOT / "tests/fixtures/authority-ir-v1.json"),
                *delegation_args(),
            ]
        )
        == EXIT_USAGE
    )
    captured = capsys.readouterr()
    assert captured.out == "" and "cannot be composed with --ir" in captured.err

    assert main(["reach", V1, *delegation_args(), *condition_args()]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == "" and "cannot yet be composed safely" in captured.err


def test_producers_validate_is_structural_only(capsys, tmp_path):
    assert main(["producers", "validate", str(PRODUCER_BOUNDARY)]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "valid producer boundary v1\n"
    assert captured.err == ""

    invalid = tmp_path / "boundary.json"
    invalid.write_text("{}", encoding="utf-8")
    assert main(["producers", "validate", str(invalid)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "missing field" in captured.err

    assert main(["producers", "validate", str(tmp_path / "absent.json")]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


@pytest.mark.parametrize(
    ("artifact", "label"),
    [
        ("continuity-binding-v1.json", "continuity binding"),
        ("agentcore-continuity-v1.json", "AgentCore continuity profile"),
        ("anthropic-continuity-v1.json", "Anthropic continuity profile"),
    ],
)
def test_continuity_validate_is_structural_only(artifact, label, capsys):
    path = ROOT / "tests/fixtures" / artifact

    assert main(["continuity", "validate", str(path)]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == f"valid {label} v1\n"
    assert captured.err == ""


def test_continuity_validate_rejects_unknown_or_malformed_artifacts(tmp_path, capsys):
    cases = ["{", "[]", "{}", '{"continuity_binding_version":1,"agentcore_continuity_version":1}']
    for index, content in enumerate(cases):
        path = tmp_path / f"invalid-{index}.json"
        path.write_text(content, encoding="utf-8")
        assert main(["continuity", "validate", str(path)]) == EXIT_USAGE
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "error:" in captured.err

    assert main(["continuity", "validate", str(tmp_path / "absent")]) == EXIT_USAGE
    assert capsys.readouterr().out == ""


def test_continuity_reconcile_emits_complete_json_and_human_output(capsys):
    command = [
        "continuity",
        "reconcile",
        str(CONTINUITY_MANIFEST.relative_to(ROOT)),
        *continuity_args(),
    ]
    assert main([*command, "--json"]) == EXIT_OK
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["schema"] == "agentmandate.continuity/v1"
    assert payload["authority"]["reachable_tools"] == ["bounded_action"]
    assert payload["outcomes"][0]["safe_continuation"] == "satisfied"
    assert payload["findings"] == []
    assert captured.out.endswith("\n")
    assert ContinuityResult.from_json(captured.out).to_json() == captured.out

    assert main(command) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "SATISFIED   synthetic-preserved-boundary" in captured.out
    assert "alignment complete_mediation=established (platform_verified)" in captured.out
    assert '"reachable_tools": [' in captured.out


def test_continuity_reconcile_findings_exit_one_after_complete_output(capsys):
    command = [
        "continuity",
        "reconcile",
        str(CONTINUITY_MANIFEST.relative_to(ROOT)),
        *continuity_args(binding=False),
    ]
    assert main([*command, "--json"]) == EXIT_FINDING
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["authority"]["reachable_tools"] == ["bounded_action"]
    assert payload["outcomes"][0]["safe_continuation"] == "unresolved"
    assert payload["findings"]

    assert main(command) == EXIT_FINDING
    captured = capsys.readouterr()
    assert "UNRESOLVED" in captured.out
    assert "FINDING" in captured.out


@pytest.mark.parametrize(
    ("flag", "name"),
    [
        ("--cedar", "cedar"),
        ("--condition", "conditions"),
        ("--delegation", "delegations"),
        ("--ir", "ir"),
        ("--graph", "mermaid"),
        ("--otel", "otel"),
        ("--producer", "producers"),
        ("--sarif", "sarif"),
    ],
)
def test_continuity_refuses_composition_before_file_io(flag, name, monkeypatch, capsys):
    def unexpected_read(*_args, **_kwargs):
        raise AssertionError("continuity composition read an input")

    monkeypatch.setattr(Path, "read_text", unexpected_read)
    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    command = [
        "continuity",
        "reconcile",
        "absent-manifest",
        "--continuity-provider",
        "absent-provider",
        "--continuity-as-of",
        "2026-09-03T12:00:00Z",
        flag,
    ]
    assert main(command) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"cannot yet be composed with {name}" in captured.err


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--continuity-as-of", "20260903"], "YYYY-MM-DDTHH:MM:SSZ"),
        (["--continuity-source", "bad"], "LOCATOR=PATH"),
        (["--continuity-source", "=bad"], "LOCATOR=PATH"),
        (["--continuity-source", "extra=missing"], "required for"),
        (["--continuity-binding-source", "extra=missing"], "--continuity-binding is required"),
    ],
)
def test_continuity_reconcile_usage_failures_have_no_output(extra, message, capsys):
    base = [
        "continuity",
        "reconcile",
        str(CONTINUITY_MANIFEST),
        "--continuity-provider",
        str(CONTINUITY_PROVIDER),
        "--continuity-as-of",
        "2026-09-03T12:00:00Z",
    ]
    if extra[0] == "--continuity-as-of":
        base[-1] = extra[1]
    else:
        base.extend(extra)
    assert main(base) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_continuity_reconcile_rejects_bad_pairing_and_artifact_roles(capsys):
    base = [
        "continuity",
        "reconcile",
        str(CONTINUITY_MANIFEST),
        "--continuity-provider",
        str(CONTINUITY_PROVIDER),
        "--continuity-as-of",
        "2026-09-03T12:00:00Z",
    ]
    cases = [
        (
            [*base, "--continuity-binding", str(CONTINUITY_BINDING)],
            "--continuity-binding-source is required",
        ),
        (
            [
                *base[: base.index("--continuity-provider") + 1],
                str(CONTINUITY_BINDING),
                *base[base.index("--continuity-provider") + 2 :],
            ],
            "requires a provider profile",
        ),
        (
            [
                *base,
                "--continuity-binding",
                str(CONTINUITY_PROVIDER),
                "--continuity-binding-source",
                "placeholder=missing",
            ],
            "requires a binding artifact",
        ),
    ]
    for command, message in cases:
        assert main(command) == EXIT_USAGE
        captured = capsys.readouterr()
        assert captured.out == ""
        assert message in captured.err


def test_continuity_reconcile_rejects_duplicate_and_extra_source_locators(capsys):
    source = (
        "tests/fixtures/continuity-accepted-synthetic/provider-control.json="
        + str(CONTINUITY_FIXTURE / "provider-control.json")
    )
    base = [
        "continuity",
        "reconcile",
        str(CONTINUITY_MANIFEST),
        *continuity_args(binding=False),
    ]
    assert main([*base, "--continuity-source", source]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "repeats locator" in captured.err

    assert main([*base, "--continuity-source", f"extra={CONTINUITY_PROVIDER}"]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not declared" in captured.err


def test_continuity_reconcile_rejects_noncanonical_short_year(capsys):
    args = continuity_args(binding=False)
    args[args.index("--continuity-as-of") + 1] = "999-09-03T12:00:00Z"
    assert main(["continuity", "reconcile", str(CONTINUITY_MANIFEST), *args]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "YYYY-MM-DDTHH:MM:SSZ" in captured.err


def test_reach_applies_accepted_producer_boundary(capsys):
    assert main(["reach", PRODUCER_MANIFEST_INPUT, *producer_args()]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "BOUNDED     mint_access_token: concurrent maximum 2" in captured.out
    assert "no reachable breach" in captured.out

    assert main(
        ["reach", PRODUCER_MANIFEST_INPUT, *producer_args(), "--json"]
    ) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["schema"] == "agentmandate.producers/v1"
    assert payload["applied"][0]["maximum"] == 2
    assert payload["findings"] == []
    assert payload["authority"]["breaches"] == []


def test_producer_public_json_fixture_is_byte_stable(capsys):
    assert main(
        ["reach", PRODUCER_MANIFEST_INPUT, *producer_args(), "--json"]
    ) == EXIT_OK
    assert capsys.readouterr().out == PRODUCER_RESULT.read_text(encoding="utf-8")


def test_reach_producer_findings_emit_complete_output_and_exit_one(capsys):
    args = producer_args()
    selection_index = args.index("--producer-selection") + 1
    args.insert(selection_index + 1, args[selection_index])
    args.insert(selection_index + 1, "--producer-selection")

    assert main(["reach", PRODUCER_MANIFEST_INPUT, *args, "--json"]) == EXIT_FINDING
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["authority"]["breaches"]
    assert payload["applied"] == []
    assert payload["findings"][0]["code"] == "producer.selection-unresolved"
    assert len(payload["inputs"]["selections"]) == 2

    assert main(["reach", PRODUCER_MANIFEST_INPUT, *args]) == EXIT_FINDING
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "UNRESOLVED  mint_access_token (producer.selection-unresolved)" in captured.out


@pytest.mark.parametrize("format_flag", ["--sarif", "--graph"])
def test_reach_refuses_producer_formats_before_output(format_flag, capsys):
    assert main(
        ["reach", PRODUCER_MANIFEST_INPUT, *producer_args(), format_flag]
    ) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "human or --json" in captured.err


@pytest.mark.parametrize("other", ["ir", "conditions", "delegations"])
def test_reach_refuses_producer_composition_before_output(other, capsys):
    if other == "ir":
        arguments = ["reach", "--ir", "unused.json", *producer_args()]
        message = "cannot be composed with --ir"
    elif other == "conditions":
        arguments = [
            "reach",
            PRODUCER_MANIFEST_INPUT,
            *producer_args(),
            *condition_args(),
        ]
        message = "producer and conditional findings cannot yet be composed safely"
    else:
        arguments = [
            "reach",
            PRODUCER_MANIFEST_INPUT,
            *producer_args(),
            *delegation_args(),
        ]
        message = "producer and delegation findings cannot yet be composed safely"

    assert main(arguments) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


@pytest.mark.parametrize(
    ("remove", "message"),
    [
        ("--producer-boundary", "--producer-boundary is required"),
        ("--producer-source", "--producer-source is required"),
        ("--producer-selection", "--producer-selection is required"),
        ("--producer-as-of", "--producer-as-of is required"),
    ],
)
def test_reach_requires_complete_producer_option_groups(remove, message, capsys):
    args = producer_args()
    while remove in args:
        index = args.index(remove)
        del args[index : index + 2]

    assert main(["reach", PRODUCER_MANIFEST_INPUT, *args]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


@pytest.mark.parametrize("as_of", ["20260903", "2026-99-03"])
def test_reach_rejects_invalid_producer_dates(as_of, capsys):
    assert main(
        ["reach", PRODUCER_MANIFEST_INPUT, *producer_args(as_of=as_of)]
    ) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "YYYY-MM-DD" in captured.err


def test_reach_rejects_malformed_producer_boundary_without_output(tmp_path, capsys):
    invalid = tmp_path / "boundary.json"
    invalid.write_text("{}", encoding="utf-8")
    args = producer_args()
    args[args.index("--producer-boundary") + 1] = str(invalid)

    assert main(["reach", PRODUCER_MANIFEST_INPUT, *args]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "missing field" in captured.err


@pytest.mark.parametrize(
    ("selection", "message"),
    [
        ("{", "not valid JSON"),
        ("[]", "must be an object"),
        (json.dumps({"source": "a.py"}), "missing field"),
        (
            json.dumps(
                {
                    **json.loads(PRODUCER_SELECTION.read_text(encoding="utf-8")),
                    "unknown": True,
                }
            ),
            "unknown field",
        ),
        (
            json.dumps(
                {
                    **json.loads(PRODUCER_SELECTION.read_text(encoding="utf-8")),
                    "partition_binding": "secret",
                }
            ),
            "reviewed non-secret alias",
        ),
        (
            json.dumps(
                {
                    **json.loads(PRODUCER_SELECTION.read_text(encoding="utf-8")),
                    "producer_version": "other",
                }
            ),
            "does not match any",
        ),
    ],
)
def test_reach_rejects_invalid_producer_selections(selection, message, capsys):
    args = producer_args()
    args[args.index("--producer-selection") + 1] = selection

    assert main(["reach", PRODUCER_MANIFEST_INPUT, *args]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_reach_rejects_bad_producer_source_mappings(capsys, tmp_path):
    base = producer_args()
    first = base.index("--producer-source")
    cases = [
        ([*base[: first + 1], "bad", *base[first + 2 :]], "LOCATOR=PATH"),
        ([*base[: first + 1], "=bad", *base[first + 2 :]], "LOCATOR=PATH"),
        (
            [
                *base[: first + 1],
                "tests/fixtures/producer-accepted-synthetic/catalogue.json="
                + str(tmp_path / "absent.json"),
                *base[first + 2 :],
            ],
            "error:",
        ),
        ([*base[:first], *base[first + 2 :]], "required for reviewed locator"),
        (
            [*base, "--producer-source", f"undeclared={PRODUCER_SELECTION}"],
            "undeclared locator",
        ),
        (
            [
                *base,
                "--producer-source",
                "tests/fixtures/producer-accepted-synthetic/catalogue.json="
                + str(PRODUCER_SELECTION),
            ],
            "different source bytes",
        ),
    ]
    for args, message in cases:
        assert main(["reach", PRODUCER_MANIFEST_INPUT, *args]) == EXIT_USAGE
        captured = capsys.readouterr()
        assert captured.out == "" and message in captured.err


def test_reach_applies_reviewed_conditional_authority(tmp_path, capsys):
    manifest = write_conditional_manifest(tmp_path)

    assert main(["reach", str(manifest), *condition_args()]) == EXIT_OK
    output = capsys.readouterr().out
    assert "APPLIED     run_query: irreversible -> read" in output
    assert "no reachable breach" in output

    assert main(["reach", str(manifest), *condition_args(), "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ungated_irreversible"] == []
    assert payload["conditions"]["schema"] == "agentmandate.conditions/v1"
    assert payload["conditions"]["as_of"] == "2027-01-01"
    assert payload["conditions"]["findings"] == []
    assert payload["conditions"]["applied"][0]["support"]


def test_conditional_public_json_fixtures_are_byte_stable(capsys):
    assert main(
        ["reach", str(CONDITIONAL_MANIFEST_PATH), *condition_args(), "--json"]
    ) == EXIT_OK
    assert capsys.readouterr().out == CONDITIONAL_REACH_RESULT.read_text(encoding="utf-8")

    assert main(
        [
            "drift",
            str(CONDITIONAL_MANIFEST_PATH),
            "--source",
            str(CONDITIONAL_SOURCE),
            *condition_args(),
            "--json",
        ]
    ) == EXIT_OK
    assert capsys.readouterr().out == CONDITIONAL_DRIFT_RESULT.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("context", "capture", "as_of", "message"),
    [
        (CONTEXT, CONDITION_CAPTURE, "2026-09-01", "not complete"),
        (CONTEXT_COMPLETE, ROOT / "README.md", "2027-01-01", "failed verification"),
        (CONTEXT_COMPLETE, CONDITION_CAPTURE, "2028-01-01", "expired"),
    ],
)
def test_reach_condition_uncertainty_is_a_finding_at_full_authority(
    tmp_path, context, capture, as_of, message, capsys
):
    manifest = write_conditional_manifest(tmp_path)
    args = condition_args(context, as_of=as_of)
    args[5] = str(capture)

    assert main(["reach", str(manifest), *args, "--json"]) == EXIT_FINDING
    payload = json.loads(capsys.readouterr().out)
    assert payload["ungated_irreversible"] == ["run_query"]
    assert message in payload["conditions"]["findings"][0]["message"]
    assert payload["conditions"]["applied"] == []


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (
            [
                "--condition-context",
                str(CONTEXT_COMPLETE),
                "--condition-capture",
                str(CONDITION_CAPTURE),
                "--condition-as-of",
                "2027-01-01",
            ],
            "--condition is required",
        ),
        (["--condition", str(CONDITION)], "--condition-context"),
        (
            ["--condition", str(CONDITION), "--condition-context", str(CONTEXT_COMPLETE)],
            "--condition-capture",
        ),
        (
            [
                "--condition",
                str(CONDITION),
                "--condition-context",
                str(CONTEXT_COMPLETE),
                "--condition-capture",
                str(CONDITION_CAPTURE),
            ],
            "--condition-as-of",
        ),
        (
            condition_args(as_of="20270101"),
            "YYYY-MM-DD",
        ),
        (
            condition_args(as_of="2027-99-01"),
            "YYYY-MM-DD",
        ),
    ],
)
def test_incomplete_condition_inputs_are_usage_errors(
    tmp_path, extra, message, capsys
):
    manifest = write_conditional_manifest(tmp_path)

    assert main(["reach", str(manifest), *extra]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_one_context_id_cannot_pair_with_different_capture_bytes(tmp_path, capsys):
    manifest = write_conditional_manifest(tmp_path)

    assert main(
        [
            "reach",
            str(manifest),
            "--condition",
            str(CONDITION),
            "--condition-context",
            str(CONTEXT_COMPLETE),
            "--condition-capture",
            str(CONDITION_CAPTURE),
            "--condition-context",
            str(CONTEXT_COMPLETE),
            "--condition-capture",
            str(ROOT / "README.md"),
            "--condition-as-of",
            "2027-01-01",
        ]
    ) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "one id supplied different capture bytes" in captured.err


@pytest.mark.parametrize("output", ["--sarif", "--graph"])
def test_condition_findings_refuse_unsupported_output_formats(
    tmp_path, output, capsys
):
    manifest = write_conditional_manifest(tmp_path)

    assert main(["reach", str(manifest), *condition_args(), output]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "human or --json" in captured.err


def test_ir_reach_refuses_standalone_condition_composition(capsys):
    assert main(
        ["reach", "--ir", "unused.json", *condition_args()]
    ) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot be composed with --ir" in captured.err


def test_diff_flags_the_read_only_addition_as_widening(capsys):
    assert main(["diff", V1, V2]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "verdict: WIDENING" in out
    assert "gained search_cases" in out


def test_diff_of_a_manifest_against_itself_passes(capsys):
    assert main(["diff", V1, V1]) == EXIT_OK
    assert "verdict: NEUTRAL" in capsys.readouterr().out


def test_verify_reports_violations_against_recorded_calls(capsys):
    assert main(["verify", V1, "--traces", TRACES]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "undeclared_tool" in out
    assert "ceiling_exceeded" in out


def test_verify_passes_on_a_conformant_record(tmp_path, capsys):
    path = tmp_path / "ok.jsonl"
    path.write_text(
        '{"tool": "open_case", "scope": "c1", "principal": "caller"}\n',
        encoding="utf-8",
    )
    assert main(["verify", V1, "--traces", str(path)]) == EXIT_OK
    assert "within the declared mandate" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["lint", V1, "--json"],
        ["reach", V2, "--json"],
        ["diff", V1, V2, "--json"],
        ["verify", V1, "--traces", TRACES, "--json"],
    ],
)
def test_every_command_emits_parseable_json(argv, capsys):
    main(argv)
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)


def test_a_missing_manifest_is_a_usage_error(capsys):
    assert main(["lint", "no-such-file.yaml"]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_a_malformed_manifest_is_a_usage_error(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"agent": "a"}', encoding="utf-8")
    assert main(["lint", str(path)]) == EXIT_USAGE
    assert "tools must be" in capsys.readouterr().err


def test_a_malformed_manifest_on_the_diff_path_is_a_usage_error(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")
    assert main(["diff", str(path), V1]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_diff_of_different_agents_is_a_usage_error(tmp_path, capsys):
    other = tmp_path / "other.yaml"
    other.write_text(
        Path(V1).read_text(encoding="utf-8").replace(
            "agent: dispute-resolver", "agent: another"
        ),
        encoding="utf-8",
    )
    assert main(["diff", V1, str(other)]) == EXIT_USAGE
    assert "cannot compare different agents" in capsys.readouterr().err


def test_a_malformed_trace_is_a_usage_error(tmp_path, capsys):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"tool": "open_case", "approved": "yes"}\n', encoding="utf-8")
    assert main(["verify", V1, "--traces", str(path)]) == EXIT_USAGE
    assert "approved must be true or false" in capsys.readouterr().err


def test_a_missing_trace_is_a_usage_error(capsys):
    assert main(["verify", V1, "--traces", "no-such-trace.jsonl"]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_version_is_reported(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == EXIT_USAGE


CATALOGUE = str(EXAMPLES / "mcp-tools.json")


def test_scan_emits_a_manifest_skeleton(capsys):
    assert main(["scan", CATALOGUE, "--agent", "dispute-resolver"]) == EXIT_OK
    out = capsys.readouterr().out
    assert 'agent: "dispute-resolver"' in out
    assert "REVIEW" in out


def test_scan_output_is_a_loadable_manifest(capsys):
    main(["scan", CATALOGUE, "--agent", "x"])
    from agentmandate import loads

    assert loads(capsys.readouterr().out).agent == "x"


def test_scan_defaults_the_agent_name(capsys):
    main(["scan", CATALOGUE])
    assert 'agent: "unnamed-agent"' in capsys.readouterr().out


def test_scan_reports_a_missing_catalogue(capsys):
    assert main(["scan", "absent.json"]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_scan_reports_a_payload_that_is_not_a_catalogue(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"nope": 1}', encoding="utf-8")
    assert main(["scan", str(path)]) == EXIT_USAGE
    assert "tools/list payload" in capsys.readouterr().err


def test_scan_source_reads_agent_code(tmp_path, capsys):
    source = tmp_path / "agent.py"
    source.write_text(
        'from strands import Agent, tool\n\n\n'
        '@tool\n'
        'def issue_refund(case_id: str, amount: float) -> str:\n'
        '    """Refund a case."""\n\n\n'
        'agent = Agent(tools=[issue_refund])\n',
        encoding="utf-8",
    )

    assert main(["scan", "--source", str(tmp_path), "--agent", "refunds"]) == EXIT_OK
    out = capsys.readouterr().out
    assert 'name: "issue_refund"' in out
    assert 'agent: "refunds"' in out


def test_scan_source_reports_a_path_with_no_tools(tmp_path, capsys):
    (tmp_path / "plain.py").write_text("x = 1\n", encoding="utf-8")

    assert main(["scan", "--source", str(tmp_path)]) == EXIT_USAGE
    assert "no tool declarations" in capsys.readouterr().err


def test_scan_requires_exactly_one_input():
    # Accepting both would silently scan one and ignore the other.
    with pytest.raises(SystemExit):
        main(["scan", CATALOGUE, "--source", "src"])
    with pytest.raises(SystemExit):
        main(["scan"])


def test_diff_record_emits_a_change_record(capsys):
    assert main(["diff", V1, V2, "--record"]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "# Agent authority change record" in out
    assert "## Authority gained" in out
    assert "named reviewer" in out


def test_reach_reports_an_ungated_irreversible_path(capsys):
    assert main(["reach", SOD]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "close_ledger_entry is irreversible and needs no approval" in out
    # The value of this over the lint rule is the route, so the route has to
    # be in the output.
    assert "1. open_case" in out


def test_a_non_positive_depth_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["reach", V2, "--depth", "0"])
    assert exit_info.value.code == EXIT_USAGE
    assert "positive integer" in capsys.readouterr().err


REVIEWED = str(EXAMPLES / "reviewed-obligations.json")


def test_obligations_exits_non_zero_until_decisions_are_mapped(capsys):
    assert main(["obligations", V1]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "irreversible:issue_refund" in out
    assert "REVIEW: map a decision" in out


def test_a_stale_review_cannot_generate_a_suite(tmp_path, capsys):
    """The blocker: a review from a different manifest would otherwise
    generate a suite for authority the agent no longer has."""
    renamed = tmp_path / "renamed.yaml"
    renamed.write_text(
        Path(V1).read_text(encoding="utf-8").replace("issue_refund", "issue_payout"),
        encoding="utf-8",
    )

    assert main(["obligations", str(renamed), "--reviewed", REVIEWED, "--suite"]) == EXIT_FINDING
    assert "issue_payout" in capsys.readouterr().err


def test_obligations_pass_once_every_row_is_reviewed(capsys):
    assert main(["obligations", V1, "--reviewed", REVIEWED]) == EXIT_OK
    assert "REVIEW: map a decision" not in capsys.readouterr().out


def test_obligations_emit_a_decision_suite_from_reviewed_rows(capsys):
    assert main(["obligations", V1, "--reviewed", REVIEWED, "--suite"]) == EXIT_OK
    suite = json.loads(capsys.readouterr().out)

    assert suite["schema"] == "agentverity.decision-suite/v1"
    assert suite["contract"]["allowed"] == ["refund_approved"]


def test_a_suite_is_refused_before_review(capsys):
    assert main(["obligations", V1, "--suite"]) == EXIT_FINDING
    assert "not fully reviewed yet" in capsys.readouterr().err


def test_obligations_emit_parseable_json(capsys):
    main(["obligations", V1, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"].startswith("agentmandate.obligations/")


def test_lint_json_reports_the_full_service_principal_finding(tmp_path, capsys):
    text = """
version: 1
agent: a
limits: {depth: 4}
tools:
  - name: ledger
    effect: write
    principal: service
    requires: [case]
"""
    manifest = tmp_path / "service-principal.yaml"
    manifest.write_text(text, encoding="utf-8")
    assert main(["lint", str(manifest), "--json"]) == EXIT_FINDING
    payload = json.loads(capsys.readouterr().out)

    finding = next(
        f for f in payload["findings"] if f["rule"] == "identity.service-principal"
    )
    assert finding["rule"] == "identity.service-principal"
    assert finding["severity"] == "error"
    assert finding["subject"] == "ledger"
    assert "confused-deputy" in finding["message"]
    assert "not always available" in finding["message"]
    assert "named review" in finding["message"]


def test_scenarios_export_the_reachable_breach_for_review(capsys):
    assert main(["scenarios", V2]) == EXIT_FINDING
    output = capsys.readouterr().out

    assert "cumulative_value:" in output
    assert "open_case -> search_cases -> issue_refund" in output
    assert "REVIEW: write the input" in output


def test_scenarios_emit_parseable_json(capsys):
    assert main(["scenarios", V2, "--json"]) == EXIT_FINDING
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == "agentmandate.scenarios/v1"
    assert payload["scenarios"][0]["agent_input"] == ""


def test_scenarios_write_a_neutral_file(tmp_path, capsys):
    output = tmp_path / "scenarios.json"

    assert main(["scenarios", V2, "--output", str(output)]) == EXIT_FINDING

    payload = json.loads(output.read_text())
    assert payload["scenarios"]
    assert "need review" in capsys.readouterr().out


def test_scenarios_reconcile_reviewed_application_fields(tmp_path, capsys):
    from agentmandate import (
        Scenario,
        ScenarioSet,
        derive_scenarios,
        load,
        save_scenarios,
    )

    scenarios = derive_scenarios(load(V2))
    reviewed = ScenarioSet(
        scenarios.agent,
        scenarios.depth,
        scenarios.truncated,
        tuple(
            Scenario(
                scenario.kind,
                scenario.detail,
                scenario.path,
                environment=("two approved cases exist",),
                agent_input="Refund both cases.",
                expected_control="block the second refund",
            )
            for scenario in scenarios.scenarios
        ),
    )
    review_path = tmp_path / "reviewed.json"
    save_scenarios(reviewed, review_path)

    assert main(["scenarios", V2, "--reviewed", str(review_path)]) == EXIT_FINDING
    assert "REVIEW:" not in capsys.readouterr().out


def test_scenarios_report_bad_review_and_output_paths(tmp_path, capsys):
    assert main(["scenarios", V2, "--reviewed", "missing.json"]) == EXIT_USAGE
    assert "cannot load scenarios" in capsys.readouterr().err

    directory = tmp_path / "directory"
    directory.mkdir()
    assert main(["scenarios", V2, "--output", str(directory)]) == EXIT_USAGE
    assert "cannot write scenarios" in capsys.readouterr().err


def test_a_malformed_reviewed_file_is_a_usage_error(tmp_path, capsys):
    bad = tmp_path / "reviewed.json"
    bad.write_text("{not json", encoding="utf-8")

    assert main(["obligations", V1, "--reviewed", str(bad)]) == EXIT_USAGE
    assert "cannot load obligations" in capsys.readouterr().err


OTEL = str(EXAMPLES / "otel-trace.json")
OTEL_MAP = [
    "--map", "scope=app.case.id", "--map", "value=app.refund.amount",
    "--map", "currency=app.currency", "--map", "approved=app.approved",
    "--map", "principal=app.principal",
]


def test_verify_reads_an_otel_trace_directly(capsys):
    assert main(["verify", V1, "--otel", OTEL, *OTEL_MAP]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "3 tool call(s)" in out
    assert "ceiling_exceeded" in out


def test_the_conversion_summary_precedes_the_verdict(capsys):
    """Two observations recovered from four hundred spans is usually a
    mapping mistake, and a clean report on almost no evidence should not
    read as success."""
    main(["verify", V1, "--otel", OTEL, *OTEL_MAP])
    out = capsys.readouterr().out
    assert out.index("read 5 span(s)") < out.index("replayed")


def test_an_unmapped_trace_fails_closed_and_says_which_fields(capsys):
    assert main(["verify", V1, "--otel", OTEL]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "no attribute mapped for" in out
    assert "missing_principal" in out


def test_emit_round_trips_to_the_plain_replay_format(tmp_path, capsys):
    out_path = tmp_path / "observed.jsonl"
    main(["verify", V1, "--otel", OTEL, *OTEL_MAP, "--emit", str(out_path)])
    capsys.readouterr()

    lines = [json.loads(x) for x in out_path.read_text().splitlines()]
    assert [row["tool"] for row in lines] == ["open_case", "issue_refund", "issue_refund"]
    # an absent field stays absent rather than becoming null
    assert "value" not in lines[0]

    assert main(["verify", V1, "--traces", str(out_path)]) == EXIT_FINDING
    assert "ceiling_exceeded" in capsys.readouterr().out


def test_a_trace_and_a_jsonl_file_cannot_both_be_given():
    with pytest.raises(SystemExit) as exit_info:
        main(["verify", V1, "--traces", TRACES, "--otel", OTEL])
    assert exit_info.value.code == EXIT_USAGE


def test_one_source_is_required():
    with pytest.raises(SystemExit) as exit_info:
        main(["verify", V1])
    assert exit_info.value.code == EXIT_USAGE


def test_a_malformed_trace_file_is_a_usage_error(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["verify", V1, "--otel", str(bad)]) == EXIT_USAGE
    assert "ExportTraceServiceRequest" in capsys.readouterr().err


def test_a_malformed_mapping_is_a_usage_error(capsys):
    assert main(["verify", V1, "--otel", OTEL, "--map", "nonsense"]) == EXIT_USAGE
    assert "malformed mapping" in capsys.readouterr().err


def test_two_independent_traces_do_not_share_a_budget(tmp_path, capsys):
    """The blocker: two runs each under the ceiling were combined into one
    breach that neither run committed."""
    def refund(trace, start):
        return {
            "name": "execute_tool issue_refund", "traceId": trace,
            "startTimeUnixNano": str(start),
            "attributes": [
                {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
                {"key": "gen_ai.tool.name", "value": {"stringValue": "issue_refund"}},
                {"key": "app.case.id", "value": {"stringValue": "c1"}},
                {"key": "app.refund.amount", "value": {"stringValue": "300"}},
                {"key": "app.currency", "value": {"stringValue": "GBP"}},
                {"key": "app.approved", "value": {"boolValue": True}},
                {"key": "app.principal", "value": {"stringValue": "caller"}},
            ],
        }
    def opener(trace, start):
        return {
            "name": "execute_tool open_case", "traceId": trace,
            "startTimeUnixNano": str(start),
            "attributes": [
                {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
                {"key": "gen_ai.tool.name", "value": {"stringValue": "open_case"}},
                {"key": "app.case.id", "value": {"stringValue": "c1"}},
                {"key": "app.principal", "value": {"stringValue": "caller"}},
            ],
        }
    path = tmp_path / "two.json"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [
        opener("A", 100), refund("A", 200), opener("B", 300), refund("B", 400)]}]}]}),
        encoding="utf-8")

    assert main(["verify", V1, "--otel", str(path), *OTEL_MAP]) == EXIT_OK
    out = capsys.readouterr().out
    assert "2 trace(s)" in out
    assert "verified separately" in out
    assert "ceiling_exceeded" not in out


def test_json_output_carries_the_conversion_counts(tmp_path, capsys):
    """CI reads the JSON. Omitting the counts hides the warnings that explain
    a suspiciously clean result."""
    main(["verify", V1, "--otel", OTEL, *OTEL_MAP, "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"].startswith("agentmandate.verify/")
    assert payload["conversion"]["total_spans"] == 5
    assert payload["conversion"]["tool_calls"] == 3
    assert payload["conversion"]["traces"] >= 1
    assert "unmapped" in payload["conversion"]
    assert "conformance" in payload


def test_otel_only_flags_are_refused_with_a_jsonl_file(capsys):
    assert main(["verify", V1, "--traces", TRACES, "--map", "scope=x"]) == EXIT_USAGE
    assert "--otel only" in capsys.readouterr().err


def test_lenient_mode_is_opt_in(tmp_path, capsys):
    path = tmp_path / "bare.json"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "t", "traceId": "t1", "startTimeUnixNano": "1", "attributes": [
            {"key": "gen_ai.tool.name", "value": {"stringValue": "open_case"}}]}]}]}]}),
        encoding="utf-8")

    main(["verify", V1, "--otel", str(path)])
    assert "0 tool call(s)" in capsys.readouterr().out

    main(["verify", V1, "--otel", str(path), "--lenient-tool-spans"])
    assert "1 tool call(s)" in capsys.readouterr().out


def test_newline_delimited_requests_are_accepted(tmp_path, capsys):
    """OpenTelemetry's file exporter writes one request per line."""
    one = json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "e", "traceId": "t1", "startTimeUnixNano": "1", "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "open_case"}},
            {"key": "app.principal", "value": {"stringValue": "caller"}}]}]}]}]})
    path = tmp_path / "ndjson.json"
    path.write_text(one + "\n" + one + "\n", encoding="utf-8")

    main(["verify", V1, "--otel", str(path), *OTEL_MAP])
    assert "2 tool call(s)" in capsys.readouterr().out


def test_an_errored_call_survives_the_emit_round_trip(tmp_path, capsys):
    """The errored flag has to reach the emitted file, or a re-run from it
    would silently pass where the trace did not."""
    path = tmp_path / "err.json"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "e", "traceId": "t1", "startTimeUnixNano": "1",
        "status": {"code": "STATUS_CODE_ERROR"},
        "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "issue_refund"}},
            {"key": "app.principal", "value": {"stringValue": "caller"}}]}]}]}]}),
        encoding="utf-8")
    out_path = tmp_path / "observed.jsonl"

    main(["verify", V1, "--otel", str(path), *OTEL_MAP, "--emit", str(out_path)])
    capsys.readouterr()

    assert json.loads(out_path.read_text().splitlines()[0])["errored"] is True
    assert main(["verify", V1, "--traces", str(out_path)]) == EXIT_FINDING
    assert "errored_effect" in capsys.readouterr().out


def test_binding_flags_are_refused_with_a_catalogue(capsys):
    assert main(["scan", CATALOGUE, "--binding", "x"]) == EXIT_USAGE
    assert "apply to --source" in capsys.readouterr().err


def test_scan_source_refuses_two_agents_and_names_them(tmp_path, capsys):
    (tmp_path / "agent.py").write_text(
        "from strands import Agent, tool\n\n\n"
        "@tool\n"
        "def a(case_id: str) -> str:\n"
        '    """A."""\n\n\n'
        "@tool\n"
        "def b(case_id: str) -> str:\n"
        '    """B."""\n\n\n'
        "triage = Agent(tools=[a])\n"
        "resolver = Agent(tools=[b])\n",
        encoding="utf-8",
    )

    assert main(["scan", "--source", str(tmp_path)]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "more than one agent" in err
    assert "triage" in err and "resolver" in err

    assert main(["scan", "--source", str(tmp_path), "--binding", "resolver"]) == EXIT_OK
    assert 'name: "b"' in capsys.readouterr().out


DRIFT_SOURCE = (
    "from strands import Agent, tool\n\n\n"
    "@tool\n"
    "def open_case(customer_id: str) -> str:\n"
    '    """Open."""\n\n\n'
    "@tool\n"
    "def wipe(case_id: str) -> None:\n"
    '    """Undeclared."""\n\n\n'
    "agent = Agent(tools=[open_case, wipe])\n"
)


def test_drift_reports_a_tool_the_mandate_never_declared(tmp_path, capsys):
    (tmp_path / "agent.py").write_text(DRIFT_SOURCE, encoding="utf-8")

    assert main(["drift", V1, "--source", str(tmp_path)]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "UNDECLARED  wipe" in out
    assert "smaller graph than the real one" in out


def test_drift_emits_parseable_json(tmp_path, capsys):
    (tmp_path / "agent.py").write_text(DRIFT_SOURCE, encoding="utf-8")

    main(["drift", V1, "--source", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["clean"] is False
    assert "wipe" in payload["discovered"]
    assert "inventory_as_of" not in payload
    assert any(f["kind"] == "undeclared" for f in payload["findings"])


def test_drift_reports_an_unreadable_source_as_a_usage_error(capsys):
    assert main(["drift", V1, "--source", "no-such-directory"]) == EXIT_USAGE
    assert "does not exist" in capsys.readouterr().err


@pytest.mark.parametrize("fixture", [AGENTKIT_INVENTORY, SENTRY_INVENTORY])
def test_inventory_validate_checks_both_evidence_declarations(fixture, capsys):
    assert main(["inventory", "validate", str(fixture)]) == EXIT_OK
    assert capsys.readouterr().out == "valid dynamic inventory v1\n"


def test_inventory_validate_failure_emits_no_stdout(tmp_path, capsys):
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"inventory_version":1,"unexpected":true}', encoding="utf-8")

    assert main(["inventory", "validate", str(invalid)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def test_drift_accepts_complete_reviewed_dynamic_inventory(tmp_path, capsys):
    source = tmp_path / "python/examples/strands-agents-cdp-server-chatbot"
    source.mkdir(parents=True)
    (source / "chatbot.py").write_text(
        "tools = get_strands_tools(agentkit)\nagent = Agent(tools=tools)\n",
        encoding="utf-8",
    )
    selection = json.dumps(
        {
            "provider": [
                "cdp_api",
                "compound",
                "erc20",
                "pyth",
                "wallet",
                "weth",
                "wow",
            ]
        }
    )

    assert main(
        [
            "drift",
            str(ROOT / "docs/evidence/agentkit/mandate.yaml"),
            "--source",
            str(tmp_path),
            "--binding",
            "agent",
            "--inventory-declaration",
            str(AGENTKIT_INVENTORY),
            "--inventory-capture",
            str(ROOT / "docs/evidence/agentkit/inventory-v074.json"),
            "--inventory-selection",
            selection,
            "--inventory-as-of",
            "2027-01-01",
            "--json",
        ]
    ) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["clean"] is True
    assert payload["inventory_as_of"] == "2027-01-01"
    assert len(payload["discovered"]) == 20


def test_drift_reconciles_condition_decisions_in_a_separate_output_section(
    tmp_path, capsys
):
    manifest = write_conditional_manifest(tmp_path)
    source = write_conditional_source(tmp_path)
    argv = ["drift", str(manifest), "--source", str(source), *condition_args()]

    assert main(argv) == EXIT_OK
    output = capsys.readouterr().out
    assert output.startswith("conditions  evaluated as of 2027-01-01")
    assert "APPLIED     run_query: irreversible -> read" in output
    assert "\ndrift  sql-agent\n" in output

    assert main([*argv, "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["clean"] is True
    assert payload["conditions"]["schema"] == "agentmandate.conditions/v1"
    assert payload["conditions"]["applied"][0]["tool"] == "run_query"
    assert payload["conditions"]["findings"] == []


def test_condition_finding_makes_combined_drift_json_unclean(tmp_path, capsys):
    manifest = write_conditional_manifest(tmp_path)
    source = write_conditional_source(tmp_path)

    assert main(
        [
            "drift",
            str(manifest),
            "--source",
            str(source),
            *condition_args(CONTEXT, as_of="2026-09-01"),
            "--json",
        ]
    ) == EXIT_FINDING
    payload = json.loads(capsys.readouterr().out)
    assert payload["clean"] is False
    assert payload["source_drift_clean"] is True
    assert payload["conditions"]["applied"] == []
    assert "not complete" in payload["conditions"]["findings"][0]["message"]


def test_multi_agent_condition_drift_explains_how_to_select_a_binding(
    tmp_path, capsys
):
    manifest = write_conditional_manifest(tmp_path)
    source = write_conditional_source(tmp_path)
    other = source / "other.py"
    other.write_text(
        "from strands import Agent, tool\n\n"
        "@tool\n"
        "def lookup() -> str:\n"
        "    return 'ok'\n\n"
        "other = Agent(tools=[lookup])\n",
        encoding="utf-8",
    )

    assert main(
        [
            "drift",
            str(manifest),
            "--source",
            str(source),
            "--union-bindings",
            *condition_args(),
        ]
    ) == EXIT_FINDING
    output = capsys.readouterr().out
    assert "UNRESOLVED  run_query" in output
    assert "select one with --binding rather than --union-bindings" in output


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ([], "--inventory-capture"),
        (
            ["--inventory-capture", "missing"],
            "--inventory-selection",
        ),
        (
            [
                "--inventory-capture",
                "missing",
                "--inventory-selection",
                "{}",
            ],
            "--inventory-as-of",
        ),
        (
            [
                "--inventory-capture",
                "missing",
                "--inventory-selection",
                "{",
                "--inventory-as-of",
                "2027-01-01",
            ],
            "valid JSON",
        ),
        (
            [
                "--inventory-capture",
                "missing",
                "--inventory-selection",
                "[]",
                "--inventory-as-of",
                "2027-01-01",
            ],
            "JSON object",
        ),
        (
            [
                "--inventory-capture",
                "missing",
                "--inventory-selection",
                "{}",
                "--inventory-as-of",
                "not-a-date",
            ],
            "YYYY-MM-DD",
        ),
        (
            [
                "--inventory-capture",
                "missing",
                "--inventory-selection",
                "{}",
                "--inventory-as-of",
                "20270101",
            ],
            "YYYY-MM-DD",
        ),
    ],
)
def test_dynamic_inventory_option_errors_emit_no_stdout(tmp_path, capsys, extra, message):
    (tmp_path / "agent.py").write_text(
        "def open_case(): pass\nagent = Agent(tools=[open_case])\n",
        encoding="utf-8",
    )
    arguments = [
        "drift",
        V1,
        "--source",
        str(tmp_path),
        "--inventory-declaration",
        str(AGENTKIT_INVENTORY),
        *extra,
    ]

    assert main(arguments) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_dynamic_inventory_requires_a_declaration(tmp_path, capsys):
    (tmp_path / "agent.py").write_text(
        "def open_case(): pass\nagent = Agent(tools=[open_case])\n",
        encoding="utf-8",
    )

    assert main(
        ["drift", V1, "--source", str(tmp_path), "--inventory-capture", "missing"]
    ) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--inventory-declaration" in captured.err


def test_dynamic_inventory_rejects_different_bytes_for_one_locator(tmp_path, capsys):
    source = tmp_path / "python/examples/strands-agents-cdp-server-chatbot"
    source.mkdir(parents=True)
    (source / "chatbot.py").write_text(
        "tools = get_strands_tools(agentkit)\nagent = Agent(tools=tools)\n",
        encoding="utf-8",
    )
    changed = tmp_path / "changed.json"
    changed.write_text("{}", encoding="utf-8")
    capture = ROOT / "docs/evidence/agentkit/inventory-v074.json"

    assert main(
        [
            "drift",
            str(ROOT / "docs/evidence/agentkit/mandate.yaml"),
            "--source",
            str(tmp_path),
            "--binding",
            "agent",
            "--inventory-declaration",
            str(AGENTKIT_INVENTORY),
            "--inventory-capture",
            str(capture),
            "--inventory-declaration",
            str(AGENTKIT_INVENTORY),
            "--inventory-capture",
            str(changed),
            "--inventory-selection",
            '{"provider":"cdp_api"}',
            "--inventory-as-of",
            "2027-01-01",
        ]
    ) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "different capture bytes" in captured.err


def test_dynamic_inventory_text_records_the_evaluation_date(tmp_path, capsys):
    source = tmp_path / "python/examples/strands-agents-cdp-server-chatbot"
    source.mkdir(parents=True)
    (source / "chatbot.py").write_text(
        "tools = get_strands_tools(agentkit)\nagent = Agent(tools=tools)\n",
        encoding="utf-8",
    )
    declaration = json.loads(AGENTKIT_INVENTORY.read_text(encoding="utf-8"))

    main(
        [
            "drift",
            str(ROOT / "docs/evidence/agentkit/mandate.yaml"),
            "--source",
            str(tmp_path),
            "--binding",
            "agent",
            "--inventory-declaration",
            str(AGENTKIT_INVENTORY),
            "--inventory-capture",
            str(ROOT / "docs/evidence/agentkit/inventory-v074.json"),
            "--inventory-selection",
            json.dumps(declaration["selection"]),
            "--inventory-as-of",
            "2027-01-01",
        ]
    )
    assert "dynamic inventory evaluated as of 2027-01-01" in capsys.readouterr().out


def test_reach_emits_sarif(capsys):
    assert main(["reach", V2, "--sarif"]) == EXIT_FINDING
    log = json.loads(capsys.readouterr().out)

    assert log["version"] == "2.1.0"
    assert log["runs"][0]["results"][0]["level"] == "error"


def test_reach_emits_a_mermaid_graph(capsys):
    assert main(["reach", V2, "--graph"]) == EXIT_FINDING
    out = capsys.readouterr().out

    assert out.startswith("flowchart LR")
    assert "--> breach" in out


def test_reach_refuses_two_output_formats(capsys):
    # Each writes to stdout. Emitting two would produce a file that is neither.
    assert main(["reach", V2, "--sarif", "--graph"]) == EXIT_USAGE
    assert "choose one output format" in capsys.readouterr().err
