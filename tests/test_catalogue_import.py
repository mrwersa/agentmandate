import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from agentmandate import analyse, check, collect, load, loads, propose, render, scan_file
from agentmandate._catalogue import import_inventory, read_catalogue
from agentmandate._inventory import _validate_inventory_profile, reconcile
from agentmandate._ir import AuthorityIR, _analyse_ir, _from_mandate
from agentmandate.cli import EXIT_FINDING, EXIT_OK, EXIT_USAGE, main

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/catalogue-import"
FIXTURES = ROOT / "tests/fixtures/catalogue-import"


def raw(format):
    return json.loads((EXAMPLE / f"{format}.json").read_bytes())


def encoded(value):
    return json.dumps(value).encode()


def declaration(format="mcp", content=None, **options):
    return import_inventory(
        content if content is not None else (EXAMPLE / f"{format}.json").read_bytes(),
        format,
        boundary=f"example-{format}",
        target_source="agent.py",
        target_binding="resolver",
        locator=f"examples/catalogue-import/{format}.json",
        selection={"environment": "example"},
        **options,
    )


def import_args(format):
    result = [
        "inventory",
        "import",
        str(EXAMPLE / f"{format}.json"),
        "--format",
        format,
        "--boundary",
        f"example-{format}",
        "--target-source",
        "agent.py",
        "--target-binding",
        "resolver",
        "--locator",
        f"examples/catalogue-import/{format}.json",
        "--selection",
        '{"environment":"example"}',
    ]
    if format == "a2a":
        result.extend(["--dispatch-tool", "ask_refund_agent"])
    return result


@pytest.mark.parametrize("format", ["mcp", "a2a", "openapi"])
def test_imported_baselines_keep_existing_contracts_and_do_not_authorize_analysis(format):
    options = {"dispatch_tool": "ask_refund_agent"} if format == "a2a" else {}
    value = declaration(format, **options)
    assert value.to_json() == (FIXTURES / f"{format}-inventory-v1.json").read_text()
    assert value.inventory_version == 1
    assert value.evidence.review == "unreviewed"
    assert value.evidence.reviewer is None and value.evidence.expires is None
    assert value.membership.completeness == "unknown"
    value.verify_source((EXAMPLE / f"{format}.json").read_bytes())
    graph = value.to_ir()
    _validate_inventory_profile(graph)
    assert graph.to_json() == (FIXTURES / f"{format}-inventory-ir-v1.json").read_text()
    assert AuthorityIR.from_json(graph.to_json()).to_json() == graph.to_json()
    with pytest.raises(ValueError, match="manifest-v1"):
        _analyse_ir(graph)


@pytest.mark.parametrize("format", ["mcp", "a2a", "openapi"])
def test_unreviewed_import_cannot_discharge_dynamic_binding_uncertainty(format):
    options = {"dispatch_tool": "ask_refund_agent"} if format == "a2a" else {}
    value = declaration(format, **options)
    inventory = collect(EXAMPLE)
    result = reconcile(
        inventory,
        [value],
        {value.source.locator: (EXAMPLE / f"{format}.json").read_bytes()},
        selection={"environment": "example"},
        as_of=date(2026, 10, 10),
    )
    assert result.complete is False and result.covers_binding is True
    assert set(result.members) == set(value.membership.members)
    messages = [finding.message for finding in result.findings]
    assert any("not accepted" in message for message in messages)
    assert any("not complete" in message for message in messages)
    assert any("expired" in message for message in messages)
    if format != "mcp":
        assert any("not exact" in message for message in messages)
    tampered = reconcile(
        inventory,
        [value],
        {value.source.locator: b"tampered"},
        selection={"environment": "example"},
        as_of=date(2026, 10, 10),
    )
    assert tampered.members == () and tampered.complete is False


@pytest.mark.parametrize("format", ["mcp", "a2a", "openapi"])
def test_scan_and_import_commands_emit_pinned_reviewable_outputs(format, tmp_path, capsys):
    args = ["scan", str(EXAMPLE / f"{format}.json"), "--format", format, "--agent", "refunds"]
    if format == "a2a":
        args.extend(["--dispatch-tool", "ask_refund_agent"])
    assert main(args) == EXIT_OK
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == (FIXTURES / f"{format}-skeleton.yaml").read_text()
    assert loads(output.out).agent == "refunds"
    assert main(import_args(format)) == EXIT_OK
    draft = capsys.readouterr()
    assert draft.err == ""
    assert draft.out == (FIXTURES / f"{format}-inventory-v1.json").read_text()
    path = tmp_path / "draft.json"
    path.write_text(draft.out)
    assert main(["inventory", "validate", str(path)]) == EXIT_OK
    capsys.readouterr()
    assert main([*import_args(format), "--ir"]) == EXIT_OK
    ir = capsys.readouterr()
    assert ir.err == ""
    assert ir.out == (FIXTURES / f"{format}-inventory-ir-v1.json").read_text()
    path.write_text(ir.out)
    assert main(["ir", "validate", str(path)]) == EXIT_OK
    capsys.readouterr()
    assert main(["reach", "--ir", str(path), "--json"]) == EXIT_USAGE
    refusal = capsys.readouterr()
    assert refusal.out == "" and "manifest-v1" in refusal.err


def test_reviewed_example_has_identical_direct_and_ir_authority():
    manifest = load(EXAMPLE / "manifest.json")
    result = _analyse_ir(_from_mandate(manifest, content=(EXAMPLE / "manifest.json").read_bytes()))
    assert result.authority == analyse(manifest)
    assert result.authority.breaches
    assert result.authority.breaches[0].path[-1].tool == "issue_refund"


@pytest.mark.parametrize("format", ["mcp", "openapi"])
@pytest.mark.parametrize("json_output", [False, True])
def test_imported_dangling_scope_cannot_pass_lint_but_reach_stays_independent(
    format,
    json_output,
    tmp_path,
    capsys,
):
    assert (
        main(
            [
                "scan",
                str(EXAMPLE / f"{format}.json"),
                "--format",
                format,
                "--agent",
                "refunds",
            ]
        )
        == EXIT_OK
    )
    skeleton = capsys.readouterr().out
    assert "No tool in this skeleton produces 'case'" in skeleton
    assert "'issue_refund' is unreachable in the declared model" in " ".join(
        skeleton.replace("#", "").split()
    )
    assert "effect is a proposal" in skeleton
    assert all(
        line.startswith("    #")
        for line in skeleton.splitlines()
        if "unreachable in the declared model" in line or "not assess this tool" in line
    )
    path = tmp_path / "skeleton.yaml"
    path.write_text(skeleton)
    args = ["lint", str(path), *(["--json"] if json_output else [])]
    assert main(args) == EXIT_FINDING
    captured = capsys.readouterr()
    assert captured.err == ""
    if json_output:
        finding = json.loads(captured.out)["findings"][0]
        assert finding["rule"] == "scope.missing-producer"
        assert finding["severity"] == "error" and finding["subject"] == "issue_refund"
    else:
        assert "scope.missing-producer" in captured.out and "issue_refund" in captured.out
    assert main(["reach", str(path), "--json"]) == EXIT_OK
    authority = json.loads(capsys.readouterr().out)
    assert authority["reachable_tools"] == ["search_cases"]
    assert authority["breaches"] == []
    corrected = skeleton.replace(
        '  - name: "search_cases"', '  - name: "search_cases"\n    produces: case'
    )
    assert check(loads(corrected)) == []
    assert analyse(loads(corrected)).reachable_tools == frozenset({"search_cases", "issue_refund"})


def test_imported_draft_leaves_cli_drift_unresolved(tmp_path, capsys):
    draft = tmp_path / "draft.json"
    draft.write_text(declaration().to_json())
    assert (
        main(
            [
                "drift",
                str(EXAMPLE / "manifest.json"),
                "--source",
                str(EXAMPLE),
                "--binding",
                "resolver",
                "--inventory-declaration",
                str(draft),
                "--inventory-capture",
                str(EXAMPLE / "mcp.json"),
                "--inventory-selection",
                '{"environment":"example"}',
                "--inventory-as-of",
                "2026-10-10",
                "--json",
            ]
        )
        == EXIT_FINDING
    )
    result = json.loads(capsys.readouterr().out)
    assert result["clean"] is False
    assert set(result["discovered"]) == {"issue_refund", "search_cases"}


@pytest.mark.parametrize("shape", ["list", "result", "rpc"])
def test_mcp_shapes_produce_same_membership_without_trusting_annotations(shape):
    value = raw("mcp")
    tools = value["result"]["tools"]
    payload = tools if shape == "list" else value["result"] if shape == "result" else value
    catalogue = read_catalogue(encoded(payload), "mcp")
    assert catalogue.confidence == "exact" and catalogue.partial is False
    assert [proposal.name for proposal in catalogue.proposals] == ["search_cases", "issue_refund"]
    assert catalogue.proposals[1].effect == "irreversible"
    assert "requires_approval: true" in render(list(catalogue.proposals), "a")


def test_mcp_pagination_and_capture_identity_survive_projection():
    value = raw("mcp")
    value["result"]["nextCursor"] = "never-fetched"
    content = encoded(value)
    catalogue = read_catalogue(content, "mcp")
    assert catalogue.partial is True and any("partial page" in note for note in catalogue.notes)
    draft = declaration(content=content)
    assert draft.membership.completeness == "partial"
    assert draft.source.content_sha256 == hashlib.sha256(content).hexdigest()
    assert draft.evidence.review == "unreviewed"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"error": {}}, "error response"),
        ({"jsonrpc": "1.0", "result": {"tools": []}}, "unambiguous"),
        ({"jsonrpc": "2.0", "tools": [], "result": {"tools": []}}, "unambiguous"),
        ({"jsonrpc": "2.0", "result": []}, "must be an object"),
        ({"tools": None}, "must be an array"),
        ({"tools": [], "nextCursor": None}, "nextCursor"),
        ([None], "MCP tool"),
        ([{}], "MCP tool name"),
        ([{"name": "get_x", "inputSchema": []}], "inputSchema"),
        ([{"name": "x"}, {"name": "x"}], "duplicate"),
        ([], "no importable"),
    ],
)
def test_mcp_malformed_membership_is_not_silently_skipped(payload, message):
    with pytest.raises(ValueError, match=message):
        read_catalogue(encoded(payload), "mcp")


@pytest.mark.parametrize("name", ["", " x ", 1, "bad\nname", "bad\x00name", "bad\x7fname"])
def test_protocol_names_are_inert_or_rejected(name):
    with pytest.raises(ValueError, match="non-empty string"):
        read_catalogue(encoded([{"name": name}]), "mcp")


@pytest.mark.parametrize("type", [["integer", "null"], {"nested": "integer"}])
def test_non_scalar_schema_types_do_not_crash_or_supply_a_value_hint(type):
    assert (
        propose([{"name": "pay", "inputSchema": {"properties": {"amount": {"type": type}}}}])[
            0
        ].value_arg
        is None
    )


@pytest.mark.parametrize("format", ["a2a", "openapi"])
def test_opaque_and_http_inputs_cannot_claim_read_effects(format):
    options = {"dispatch_tool": "get_agent"} if format == "a2a" else {}
    catalogue = read_catalogue((EXAMPLE / f"{format}.json").read_bytes(), format, **options)
    assert all(p.effect == "irreversible" and p.guessed_effect for p in catalogue.proposals)
    if format == "a2a":
        assert [p.name for p in catalogue.proposals] == ["get_agent"]
        assert all(p.scope is None and p.value_arg is None for p in catalogue.proposals)
        assert "internal tools" in " ".join(catalogue.notes)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"protocolVersion": "1.0"}, "protocolVersion 0.3.0"),
        ({"skills": {}}, "must be an array"),
        ({"skills": [None]}, "must be an object"),
        ({"skills": [{"id": "x", "name": "X"}, {"id": "x", "name": "Y"}]}, "duplicate"),
        ({"url": "\nhttps://example.invalid"}, "A2A agent URL"),
    ],
)
def test_a2a_refuses_unsupported_or_ambiguous_cards(change, message):
    value = raw("a2a")
    value.update(change)
    with pytest.raises(ValueError, match=message):
        read_catalogue(encoded(value), "a2a", dispatch_tool="ask_agent")


def test_a2a_requires_explicit_application_dispatch_and_keeps_empty_skills_opaque():
    value = raw("a2a")
    with pytest.raises(ValueError, match="skills are not callable"):
        read_catalogue(encoded(value), "a2a")
    value["skills"] = []
    assert read_catalogue(encoded(value), "a2a", dispatch_tool="ask_agent").proposals[0].name == (
        "ask_agent"
    )


def test_a2a_current_interfaces_keep_one_opaque_candidate_and_pinned_outputs(capsys):
    content = (EXAMPLE / "a2a-1.0.json").read_bytes()
    catalogue = read_catalogue(content, "a2a", dispatch_tool="ask_refund_agent")
    assert catalogue.format_version == "A2A 1.0" and catalogue.confidence == "heuristic"
    assert [p.name for p in catalogue.proposals] == ["ask_refund_agent"]
    assert (
        main(
            [
                "scan",
                str(EXAMPLE / "a2a-1.0.json"),
                "--format",
                "a2a",
                "--dispatch-tool",
                "ask_refund_agent",
                "--agent",
                "refunds",
            ]
        )
        == EXIT_OK
    )
    assert capsys.readouterr().out == (FIXTURES / "a2a-1.0-skeleton.yaml").read_text()
    value = import_inventory(
        content,
        "a2a",
        boundary="example-a2a-1.0",
        target_source="agent.py",
        target_binding="resolver",
        locator="examples/catalogue-import/a2a-1.0.json",
        selection={"environment": "example"},
        dispatch_tool="ask_refund_agent",
    )
    assert value.to_json() == (FIXTURES / "a2a-1.0-inventory-v1.json").read_text()
    assert value.to_ir().to_json() == (FIXTURES / "a2a-1.0-inventory-ir-v1.json").read_text()
    assert value.membership.completeness == "unknown" and value.evidence.review == "unreviewed"
    value.verify_source(content)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"protocolVersion": "0.3.0"}, "mixes legacy"),
        ({"url": "https://example.invalid"}, "mixes legacy"),
        ({"supportedInterfaces": None}, "must be an array"),
        ({"supportedInterfaces": []}, "must not be empty"),
        ({"supportedInterfaces": [None]}, "must be an object"),
        ({"supportedInterfaces": [{"protocolVersion": "2.0"}]}, "protocolVersion 1.0"),
        ({"supportedInterfaces": [{"protocolVersion": "1.0", "url": ""}]}, "interface URL"),
        (
            {"supportedInterfaces": [{"protocolVersion": "1.0", "url": "https://example.invalid"}]},
            "protocol binding",
        ),
    ],
)
def test_a2a_modern_unknown_or_mixed_interfaces_are_not_silently_selected(change, message):
    value = raw("a2a-1.0")
    value.update(change)
    with pytest.raises(ValueError, match=message):
        read_catalogue(encoded(value), "a2a", dispatch_tool="ask_agent")


def test_openapi_argument_hints_do_not_import_security_or_schema_maximum():
    catalogue = read_catalogue((EXAMPLE / "openapi.json").read_bytes(), "openapi")
    refund = next(p for p in catalogue.proposals if p.name == "issue_refund")
    assert refund.scope == "case" and refund.value_arg == "amount"
    text = render(list(catalogue.proposals), "refunds", list(catalogue.notes))
    assert "ceiling: { amount: 0" in text and "amount: 500" not in text
    assert all(tool.principal == "caller" for tool in loads(text).tools)


def test_openapi_fallback_names_metadata_and_local_pointer_escaping():
    value = raw("openapi")
    operation = {"get": {"parameters": []}}
    value["paths"] = {
        "/x": {"$ref": "#/components/pathItems/x~1y~0z"},
        "x-extension": {"ignored": True},
    }
    value["components"]["pathItems"]["x/y~z"] = operation
    result = read_catalogue(encoded(value), "openapi")
    assert result.proposals[0].name == "GET /x"
    assert result.proposals[0].effect == "irreversible"


def test_openapi_parameter_overrides_and_opaque_body_schemas():
    value = raw("openapi")
    value["paths"] = {
        "/pay": {
            "parameters": [{"name": "amount", "in": "query", "schema": {"type": "integer"}}],
            "post": {
                "parameters": [
                    {"$ref": "https://example.invalid/parameter.json"},
                    {"name": "amount", "in": "query", "schema": {"type": "string"}},
                ],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "https://example.invalid/schema.json",
                                "properties": {"value": {}},
                            }
                        }
                    }
                },
            },
        }
    }
    assert read_catalogue(encoded(value), "openapi").proposals[0].value_arg is None
    value["paths"]["/pay"]["post"]["requestBody"]["$ref"] = "external.json"
    assert read_catalogue(encoded(value), "openapi").proposals[0].value_arg is None
    value["paths"]["/pay"]["post"]["requestBody"]["content"]["application/json"]["schema"] = True
    assert read_catalogue(encoded(value), "openapi").proposals[0].value_arg is None


@pytest.mark.parametrize("version", ["3.0.3", "3.1.0"])
def test_openapi_supported_version_families(version):
    value = raw("openapi")
    value["openapi"] = version
    assert read_catalogue(encoded(value), "openapi").format_version == f"OpenAPI {version}"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"openapi": "2.0"}, "3.0.x and 3.1.x"),
        ({"openapi": None}, "3.0.x and 3.1.x"),
        ({"paths": {"bad": {}}}, "start with /"),
        ({"paths": {"/bad": []}}, "Path Item"),
        ({"paths": {"/bad": {"get": None}}}, "operation"),
        ({"paths": {"/bad": {"$ref": "file:///etc/passwd"}}}, "document-local"),
        ({"paths": {"/bad": {"$ref": "#/paths/~1bad"}}}, "cycle"),
        ({"paths": {"/bad": {"$ref": "#/no/such/item"}}}, "target is missing"),
        ({"paths": {"/bad": {"$ref": "#/openapi"}}}, "target must be an object"),
        ({"paths": {"/bad": {"$ref": "#/no", "get": {}}}}, "siblings"),
        ({"paths": {"/bad": {"get": {"parameters": {}}}}}, "parameters"),
        (
            {"paths": {"/a": {"get": {"operationId": "x"}}, "/b": {"post": {"operationId": "x"}}}},
            "duplicate",
        ),
        ({"paths": {}}, "no importable"),
    ],
)
def test_openapi_bad_or_unsupported_operation_graphs_fail_closed(change, message):
    value = raw("openapi")
    value.update(change)
    with pytest.raises(ValueError, match=message):
        read_catalogue(encoded(value), "openapi")


@pytest.mark.parametrize(
    "content",
    [b'{"tools":[],"tools":[]}', b"[NaN]", b"[Infinity]", b"[1e999]"],
)
def test_ambiguous_or_non_finite_json_is_rejected(content):
    with pytest.raises(ValueError):
        read_catalogue(content, "mcp")


def test_unknown_reader_and_mismatched_dispatch_options_are_rejected():
    with pytest.raises(ValueError, match="choose catalogue format"):
        read_catalogue(b"{}", "unknown")
    with pytest.raises(ValueError, match="applies only"):
        read_catalogue(b"{}", "mcp", dispatch_tool="ask")


def test_finite_numbers_do_not_become_mandate_limits():
    value = raw("mcp")
    value["result"]["tools"][1]["inputSchema"]["properties"]["amount"]["maximum"] = 500.0
    catalogue = read_catalogue(encoded(value), "mcp")
    assert catalogue.proposals[1].value_arg == "amount"
    assert "amount: 500" not in render(list(catalogue.proposals), "a")


@pytest.mark.parametrize("payload", [b"\xff", b"{}", b"{", b"[" * 1500 + b"]" * 1500])
@pytest.mark.parametrize("command", ["scan", "inventory"])
def test_cli_encoding_malformed_and_deep_inputs_never_emit_partial_stdout(
    payload,
    command,
    tmp_path,
    capsys,
):
    path = tmp_path / "bad.json"
    path.write_bytes(payload)
    args = ["scan", str(path), "--format", "mcp"] if command == "scan" else import_args("mcp")
    if command == "inventory":
        args[2] = str(path)
    assert main(args) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("error:")


@pytest.mark.parametrize(
    "extra",
    [
        ["--source", "missing", "--format", "mcp"],
        ["--source", "missing", "--dispatch-tool", "ask"],
        [str(EXAMPLE / "mcp.json"), "--dispatch-tool", "ask"],
        [str(EXAMPLE / "mcp.json"), "--format", "mcp", "--binding", "resolver"],
    ],
)
def test_scan_incompatible_modes_emit_no_skeleton(extra, capsys):
    assert main(["scan", *extra]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("error:")


def test_import_requires_explicit_safe_target_selection_and_capture_locator(capsys):
    args = import_args("mcp")
    for option, bad in [
        ("--target-source", "../escape.py"),
        ("--locator", "/etc/passwd"),
        ("--selection", "[]"),
        ("--selection", "not-json"),
    ]:
        changed = args.copy()
        changed[changed.index(option) + 1] = bad
        assert main(changed) == EXIT_USAGE
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err.startswith("error:")


@pytest.mark.parametrize(
    "path",
    [
        ROOT / f"docs/evidence/{name}/catalogue.json"
        for name in ("aws-postgres-mcp", "aws-iam-access-keys", "initiative-mcp", "sentry-mcp")
    ],
)
def test_existing_mcp_captures_and_original_scan_output_remain_compatible(path, capsys):
    value = read_catalogue(path.read_bytes(), "mcp")
    assert list(value.proposals) == propose(json.loads(path.read_bytes()))
    assert main(["scan", str(path), "--agent", "compat"]) == EXIT_OK
    assert capsys.readouterr().out == scan_file(path, "compat")
