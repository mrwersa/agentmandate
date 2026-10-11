"""Compile the explicit stateless subset; never disguise lost sequence controls."""

from __future__ import annotations

import hashlib
import json
import re

from ._policy_export import object_fields as _object
from ._policy_export import pairs as _pairs
from ._policy_export import stateful_losses
from ._policy_export import string as _string
from ._policy_export import unused as _unused
from .manifest import loads

EXPORT_VERSION = 1
EXPORT_SCHEMA = "agentmandate.cedar-export/v1"
_RESERVED = frozenset(
    {
        "if",
        "then",
        "else",
        "in",
        "is",
        "has",
        "like",
        "true",
        "false",
        "permit",
        "forbid",
        "when",
        "unless",
        "principal",
        "action",
        "resource",
        "context",
    }
)


def _identifier(value):
    value = _string(value)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value) or value in _RESERVED:
        raise ValueError(f"invalid Cedar identifier: {value!r}")
    return value


def _mapping(content, mandate):
    value = _object(
        json.loads(content, object_pairs_hook=_pairs),
        {
            "cedar_export_version",
            "agent",
            "identity",
            "namespace",
            "principals",
            "resource",
            "actions",
            "approval_context",
        },
        "export mapping",
    )
    if type(value["cedar_export_version"]) is not int or value["cedar_export_version"] != 1:
        raise ValueError("unsupported cedar_export_version")
    if value["agent"] != mandate.agent or value["identity"] != mandate.identity:
        raise ValueError("export mapping must name the manifest agent and declared identity")
    namespace = _string(value["namespace"])
    for part in namespace.split("::"):
        _identifier(part)
    _identifier(value["approval_context"])
    principals = value["principals"]
    if not isinstance(principals, dict) or set(principals) != {t.principal for t in mandate.tools}:
        raise ValueError("export principals must map exactly the used principal classes")
    seen = set()
    for rows in principals.values():
        if not isinstance(rows, list) or not rows:
            raise ValueError("each principal class needs a non-empty entity list")
        for row in rows:
            _entity(row)
            key = (row["type"], row["id"])
            if key in seen:
                raise ValueError("export principal entities must be distinct across all classes")
            seen.add(key)
    _entity(value["resource"])
    actions = value["actions"]
    if not isinstance(actions, dict) or set(actions) != set(mandate.tool_names):
        raise ValueError("export actions must map every manifest tool exactly once")
    for action in actions.values():
        _string(action)
    if len(set(actions.values())) != len(actions):
        raise ValueError("export action IDs must be distinct")
    return value


def _entity(value):
    _object(value, {"type", "id"}, "export entity")
    if _identifier(value["type"]) == "Action":
        raise ValueError("Action is reserved for the generated action entity type")
    _string(value["id"])


def _uid(namespace, entity):
    return {"type": f"{namespace}::{entity['type']}", "id": entity["id"]}


def _literal(uid):
    return f"{uid['type']}::{json.dumps(uid['id'])}"


def export(manifest_content: bytes, mapping_content: bytes, *, allow_partial: bool = False):
    """Return deterministic policy, schema and executable request cases without running Cedar."""
    mandate = loads(manifest_content.decode("utf-8"))
    mapping = _mapping(mapping_content, mandate)
    losses = stateful_losses(mandate, "Cedar")
    result = {
        "schema": EXPORT_SCHEMA,
        "target": {
            "language_version": "4.5",
            "sdk": "@cedar-policy/cedar-wasm",
            "sdk_version": "4.12.0",
        },
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
        "policies": None,
        "cedar_schema": None,
        "entities": [],
        "tests": [],
    }
    if result["status"] == "refused":
        return result
    namespace = mapping["namespace"]
    resource = _uid(namespace, mapping["resource"])
    approval = mapping["approval_context"]
    principals = {
        kind: sorted((_uid(namespace, row) for row in rows), key=lambda u: (u["type"], u["id"]))
        for kind, rows in mapping["principals"].items()
    }
    all_principals = [uid for kind in sorted(principals) for uid in principals[kind]]
    types = {uid["type"].split("::")[-1] for uid in [*all_principals, resource]}
    schema = {namespace: {"entityTypes": {name: {} for name in sorted(types)}, "actions": {}}}
    policies = []
    tests = []
    for tool in sorted(mandate.tools, key=lambda t: t.name):
        action = {"type": f"{namespace}::Action", "id": mapping["actions"][tool.name]}
        allowed = principals[tool.principal]
        principal_set = " || ".join(f"principal == {_literal(uid)}" for uid in allowed)
        condition = (
            f" && context has {approval} && context.{approval}" if tool.requires_approval else ""
        )
        policies.append(
            f"permit(principal, action == {_literal(action)}, resource == {_literal(resource)})\n"
            f"when {{ ({principal_set}){condition} }};"
        )
        schema[namespace]["actions"][action["id"]] = {
            "appliesTo": {
                "principalTypes": sorted({uid["type"] for uid in all_principals}),
                "resourceTypes": [resource["type"]],
                "context": {
                    "type": "Record",
                    "attributes": {approval: {"type": "Boolean", "required": False}},
                },
            }
        }

        def case(label, principal, res, context, expected, *, name=tool.name, target_action=action):
            tests.append(
                {
                    "name": f"{name}:{label}",
                    "request": {
                        "principal": principal,
                        "action": target_action,
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
        outsider = {**allowed[0], "id": _unused({uid["id"] for uid in all_principals})}
        case("unmapped-principal", outsider, resource, {approval: True}, "deny")
        case(
            "other-resource",
            allowed[0],
            {**resource, "id": _unused({resource["id"]})},
            {approval: True},
            "deny",
        )
        for kind in sorted(principals):
            if kind != tool.principal:
                case(f"other-class-{kind}", principals[kind][0], resource, {approval: True}, "deny")
    entities = {(uid["type"], uid["id"]): uid for uid in [*all_principals, resource]}
    result.update(
        policies="\n\n".join(policies) + "\n",
        cedar_schema=schema,
        entities=[{"uid": entities[key], "attrs": {}, "parents": []} for key in sorted(entities)],
        tests=tests,
    )
    return result


def render(result):
    lines = [
        f"CEDAR {result['status']}",
        result["scope"],
        "Native validation: not run by this command.",
    ]
    lines.extend(
        f"LOSS {row['code']} {row['subject']}: {row['detail']}" for row in result["losses"]
    )
    if result["policies"] is not None:
        lines.extend(["", result["policies"].rstrip()])
    return "\n".join(lines) + "\n"
