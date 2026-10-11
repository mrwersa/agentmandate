"""Compile explicit stateless permissions to Rego v1, with no inferred identities."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from ._policy_export import object_fields, pairs, stateful_losses, string, unused
from ._policy_export_files import write_files
from .manifest import loads

EXPORT_VERSION = 1
EXPORT_SCHEMA = "agentmandate.rego-export/v1"
_RESERVED = frozenset(
    {
        "as",
        "contains",
        "default",
        "else",
        "every",
        "false",
        "if",
        "import",
        "in",
        "not",
        "null",
        "package",
        "some",
        "true",
        "with",
        "data",
        "input",
    }
)


def _mapping(content, mandate):
    value = object_fields(
        json.loads(content, object_pairs_hook=pairs),
        {
            "rego_export_version",
            "agent",
            "identity",
            "package",
            "principals",
            "resource",
            "actions",
            "approval_context",
        },
        "export mapping",
    )
    if type(value["rego_export_version"]) is not int or value["rego_export_version"] != 1:
        raise ValueError("unsupported rego_export_version")
    if value["agent"] != mandate.agent or value["identity"] != mandate.identity:
        raise ValueError("export mapping must name the manifest agent and declared identity")
    for part in string(value["package"]).split("."):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", part) or part in _RESERVED:
            raise ValueError(f"invalid Rego package identifier: {part!r}")
    string(value["resource"])
    string(value["approval_context"])
    principals = value["principals"]
    if not isinstance(principals, dict) or set(principals) != {t.principal for t in mandate.tools}:
        raise ValueError("export principals must map exactly the used principal classes")
    seen = set()
    for rows in principals.values():
        if not isinstance(rows, list) or not rows:
            raise ValueError("each principal class needs a non-empty identity list")
        for principal in rows:
            string(principal)
            if principal in seen:
                raise ValueError("export principal identities must be distinct across all classes")
            seen.add(principal)
    actions = value["actions"]
    if not isinstance(actions, dict) or set(actions) != set(mandate.tool_names):
        raise ValueError("export actions must map every manifest tool exactly once")
    for action in actions.values():
        string(action)
    if len(set(actions.values())) != len(actions):
        raise ValueError("export action IDs must be distinct")
    return value


def export(manifest_content: bytes, mapping_content: bytes, *, allow_partial: bool = False):
    mandate = loads(manifest_content.decode("utf-8"))
    mapping = _mapping(mapping_content, mandate)
    losses = stateful_losses(mandate, "Rego")
    result = {
        "schema": EXPORT_SCHEMA,
        "target": {"language_version": "v1", "engine": "OPA", "engine_version": "1.21.1"},
        "scope": (
            "mapped stateless per-request permissions; not deployment activation or state retention"
        ),
        "inputs": {
            "manifest_sha256": hashlib.sha256(manifest_content).hexdigest(),
            "mapping_sha256": hashlib.sha256(mapping_content).hexdigest(),
        },
        "status": "refused"
        if losses and not allow_partial
        else ("partial_export" if losses else "exported"),
        "losses": losses,
        "mapping": mapping,
        "native_validation": "not_run",
        "policy": None,
        "input_schema": None,
        "native_tests": None,
        "tests": [],
    }
    if result["status"] == "refused":
        return result
    package = mapping["package"]
    approval = mapping["approval_context"]
    resource = mapping["resource"]
    principals = {kind: sorted(rows) for kind, rows in mapping["principals"].items()}
    all_principals = {p for rows in principals.values() for p in rows}
    policies = [f"package {package}", "import rego.v1", "default allow := false"]
    tests = []
    for tool in sorted(mandate.tools, key=lambda t: t.name):
        action = mapping["actions"][tool.name]
        allowed = principals[tool.principal]
        clauses = [
            "is_object(input)",
            "is_string(input.principal)",
            "is_string(input.action)",
            "is_string(input.resource)",
            "is_object(input.context)",
            "input.principal in {" + ", ".join(json.dumps(p) for p in allowed) + "}",
            f"input.action == {json.dumps(action)}",
            f"input.resource == {json.dumps(resource)}",
        ]
        if tool.requires_approval:
            clauses.append(f"input.context[{json.dumps(approval)}] == true")
        policies.append("allow if {\n" + "\n".join(f"    {c}" for c in clauses) + "\n}")

        def case(label, principal, res, context, expected, *, name=tool.name, target=action):
            tests.append(
                {
                    "name": f"{name}:{label}",
                    "request": {
                        "principal": principal,
                        "action": target,
                        "resource": res,
                        "context": context,
                    },
                    "expected": expected,
                }
            )

        for index, principal in enumerate(allowed):
            case(f"allowed-{index}", principal, resource, {approval: True}, "allow")
        case(
            "approval-false",
            allowed[0],
            resource,
            {approval: False},
            "deny" if tool.requires_approval else "allow",
        )
        case(
            "approval-missing",
            allowed[0],
            resource,
            {},
            "deny" if tool.requires_approval else "allow",
        )
        case("unmapped-principal", unused(all_principals), resource, {approval: True}, "deny")
        case("other-resource", allowed[0], unused({resource}), {approval: True}, "deny")
        case(
            "unmapped-action",
            allowed[0],
            resource,
            {approval: True},
            "deny",
            target=unused(set(mapping["actions"].values())),
        )
        for kind in sorted(principals):
            if kind != tool.principal:
                case(f"other-class-{kind}", principals[kind][0], resource, {approval: True}, "deny")
    result.update(
        policy="\n\n".join(policies) + "\n",
        input_schema={
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": ["principal", "action", "resource", "context"],
            "properties": {
                "principal": {"type": "string"},
                "action": {"type": "string"},
                "resource": {"type": "string"},
                "context": {"type": "object", "properties": {approval: {"type": "boolean"}}},
            },
        },
        native_tests=(
            f"package {package}\n\nimport rego.v1\n\n"
            "test_generated_requests if {\n"
            "    count(data.cases) > 0\n"
            "    every test in data.cases {\n"
            '        expected := test.expected == "allow"\n'
            "        actual := allow with input as test.request\n"
            "        actual == expected\n"
            "    }\n}\n"
        ),
        tests=tests,
    )
    return result


def write_bundle(result: dict, destination: Path) -> None:
    files = {"policy.rego": result["policy"], "policy_test.rego": result["native_tests"]}
    for name, value in (
        ("schema.json", result["input_schema"]),
        ("tests.json", {"cases": result["tests"]}),
        ("export.json", result),
    ):
        files[name] = json.dumps(value, indent=2, sort_keys=True) + "\n"
    write_files(files, destination, reserve_rename=os.name != "nt")


def render(result):
    lines = [
        f"REGO {result['status']}",
        result["scope"],
        "Native validation: not run by this command.",
    ]
    lines.extend(f"LOSS {r['code']} {r['subject']}: {r['detail']}" for r in result["losses"])
    if result["policy"] is not None:
        lines.extend(["", result["policy"].rstrip()])
    return "\n".join(lines) + "\n"
