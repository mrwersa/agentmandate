"""Compare supplied deployment configuration with an independently rebuilt export."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

from ._cedar_export import export as export_cedar
from ._policy_export import object_fields, pairs, string
from ._rego_export import export as export_rego
from .manifest import loads
from .reach import analyse

DEPLOYMENT_VERSION = 1
RESULT_SCHEMA = "agentmandate.deployment-drift/v1"


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("deployment dates must use YYYY-MM-DD")
    return date.fromisoformat(value)


def _coverage(value):
    if value not in ("complete", "partial", "unknown"):
        raise ValueError("coverage must be complete, partial or unknown")


def _unique(values, *, entities=False):
    if not isinstance(values, list):
        raise ValueError("deployment identity/tool lists must be arrays")
    keys = []
    for value in values:
        if entities:
            object_fields(value, {"type", "id"}, "deployment entity")
            string(value["type"])
            string(value["id"])
        else:
            string(value)
        keys.append(json.dumps(value, sort_keys=True))
    if len(set(keys)) != len(keys):
        raise ValueError("deployment identity/tool lists must be distinct")


def _config(content):
    value = object_fields(
        json.loads(content, object_pairs_hook=pairs),
        {
            "deployment_version",
            "agent",
            "identity",
            "environment",
            "observed_at",
            "expires",
            "export",
            "inventory",
            "gateway",
            "policy",
        },
        "deployment configuration",
    )
    if type(value["deployment_version"]) is not int or value["deployment_version"] != 1:
        raise ValueError("unsupported deployment_version")
    for name in ("agent", "environment"):
        string(value[name])
    if value["identity"] is not None:
        string(value["identity"])
    if _date(value["observed_at"]) > _date(value["expires"]):
        raise ValueError("deployment expiry precedes observation date")
    export = object_fields(value["export"], {"target", "mapping", "receipt"}, "export join")
    if export["target"] not in ("cedar", "rego"):
        raise ValueError("export target must be cedar or rego")
    for field in ("mapping", "receipt"):
        string(export[field])
    inventory = object_fields(value["inventory"], {"coverage", "tools"}, "deployment inventory")
    _coverage(inventory["coverage"])
    _unique(inventory["tools"])
    policy = object_fields(value["policy"], {"revision", "coverage", "files"}, "active policy")
    string(policy["revision"])
    _coverage(policy["coverage"])
    if not isinstance(policy["files"], dict):
        raise ValueError("policy files must map artifact names to local paths")
    for name, locator in policy["files"].items():
        string(name)
        string(locator)
    gateway = object_fields(value["gateway"], {"id", "coverage", "routes"}, "gateway")
    string(gateway["id"])
    _coverage(gateway["coverage"])
    if not isinstance(gateway["routes"], list):
        raise ValueError("gateway routes must be an array")
    seen = set()
    for row in gateway["routes"]:
        object_fields(
            row,
            {
                "tool",
                "principals",
                "action",
                "resource",
                "approval_context",
                "mediation",
                "policy_revision",
            },
            "gateway route",
        )
        name = string(row["tool"])
        if name in seen:
            raise ValueError("one gateway route per tool is supported; duplicate route")
        seen.add(name)
        if row["mediation"] not in ("required", "bypassed", "unknown"):
            raise ValueError("route mediation must be required, bypassed or unknown")
        for field in ("approval_context", "policy_revision"):
            if row[field] is not None:
                string(row[field])
        cedar = export["target"] == "cedar"
        _unique(row["principals"], entities=cedar)
        for field in ("action", "resource"):
            if cedar:
                _unique([row[field]], entities=True)
            else:
                string(row[field])
    return value


def _read(root, locator):
    locator = string(locator)
    if (
        "\\" in locator
        or ":" in locator.split("/")[0]
        or any(part in ("", ".", "..") for part in locator.split("/"))
    ):
        raise ValueError("deployment paths must be normalized relative paths")
    path = (root / locator).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"deployment file must exist inside --root: {locator!r}")
    return path.read_bytes()


def _expected(tool, mapping, target, revision):
    if target == "cedar":
        namespace = mapping["namespace"]

        def uid(row):
            return {"type": f"{namespace}::{row['type']}", "id": row["id"]}

        principal = [uid(row) for row in mapping["principals"][tool.principal]]
        action = {"type": f"{namespace}::Action", "id": mapping["actions"][tool.name]}
        resource = uid(mapping["resource"])
    else:
        principal = mapping["principals"][tool.principal]
        action = mapping["actions"][tool.name]
        resource = mapping["resource"]
    return {
        "principals": principal,
        "action": action,
        "resource": resource,
        "approval_context": mapping["approval_context"] if tool.requires_approval else None,
        "policy_revision": revision,
    }


def evaluate(manifest_content: bytes, config_content: bytes, *, root: Path, as_of: str):
    """Return file/configuration drift; never infer a live policy decision or state reset."""
    today = _date(as_of)
    config = _config(config_content)
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("--root must be a deployment artifact directory")
    mandate = loads(manifest_content.decode("utf-8"))
    materials = {}

    def read(locator):
        if locator not in materials:
            materials[locator] = _read(root, locator)
        return materials[locator]

    target = config["export"]["target"]
    mapping_content = read(config["export"]["mapping"])
    receipt = json.loads(read(config["export"]["receipt"]), object_pairs_hook=pairs)
    if not isinstance(receipt, dict):
        raise ValueError("export receipt must be an object")
    expected = (export_cedar if target == "cedar" else export_rego)(
        manifest_content,
        mapping_content,
        allow_partial=True,
    )
    findings = []

    def finding(code, subject, detail):
        findings.append({"code": code, "subject": subject, "detail": detail})

    for field, actual in (("agent", mandate.agent), ("identity", mandate.identity)):
        if config[field] != actual:
            finding(
                "deployment.identity-mismatch",
                field,
                f"configuration {field} differs from the manifest",
            )
    current = _date(config["observed_at"]) <= today <= _date(config["expires"])
    if not current:
        finding(
            "deployment.snapshot-not-current",
            config["environment"],
            "evaluation date is outside the declared observation/expiry window",
        )
    for label in ("inventory", "gateway", "policy"):
        if config[label]["coverage"] != "complete":
            finding(
                "deployment.coverage-incomplete",
                label,
                f"declared {label} coverage is {config[label]['coverage']}",
            )
    if receipt != expected:
        finding(
            "deployment.export-mismatch",
            target,
            "export receipt differs from the independently rebuilt manifest/mapping result",
        )
    for loss in expected["losses"]:
        finding(
            "deployment.control-uncompiled", loss["subject"], f"{loss['code']}: {loss['detail']}"
        )

    policy_name = "policies.cedar" if target == "cedar" else "policy.rego"
    policy = expected["policies"] if target == "cedar" else expected["policy"]
    schema = expected["cedar_schema"] if target == "cedar" else expected["input_schema"]
    expected_files = {
        policy_name: policy.encode(),
        "schema.json": (json.dumps(schema, indent=2, sort_keys=True) + "\n").encode(),
    }
    artifacts = []
    supplied = config["policy"]["files"]
    for name in sorted(set(expected_files) | set(supplied)):
        expected_sha = (
            hashlib.sha256(expected_files[name]).hexdigest() if name in expected_files else None
        )
        actual_sha = hashlib.sha256(read(supplied[name])).hexdigest() if name in supplied else None
        status = (
            "matches"
            if expected_sha == actual_sha
            else (
                "unresolved"
                if actual_sha is None
                and (not current or config["policy"]["coverage"] != "complete")
                else "missing"
                if actual_sha is None
                else "extra"
                if expected_sha is None
                else "differs"
            )
        )
        artifacts.append(
            {
                "artifact": name,
                "status": status,
                "expected_sha256": expected_sha,
                "observed_sha256": actual_sha,
            }
        )
        if status != "matches":
            finding(
                "deployment.policy-" + status,
                name,
                "active artifact does not match the export; no semantic equivalence is inferred",
            )

    inventory = set(config["inventory"]["tools"])
    routes = {row["tool"]: row for row in config["gateway"]["routes"]}
    tools = {tool.name: tool for tool in mandate.tools}
    assessments = []
    for name in sorted(set(tools) | inventory | set(routes)):
        in_inventory = name in inventory
        route = routes.get(name)
        assessment = {
            "tool": name,
            "inventory_presence": "observed"
            if in_inventory
            else (
                "absent_from_complete_inventory"
                if current and config["inventory"]["coverage"] == "complete"
                else "unresolved"
            ),
            "route_presence": "observed"
            if route is not None
            else (
                "absent_from_complete_gateway"
                if current and config["gateway"]["coverage"] == "complete"
                else "unresolved"
            ),
            "expected": None,
            "observed": route,
        }
        assessments.append(assessment)
        if name not in tools:
            finding(
                "deployment.tool-undeclared",
                name,
                "supplied inventory or gateway exposes a tool the manifest does not declare",
            )
            continue
        if assessment["inventory_presence"] == "absent_from_complete_inventory":
            finding(
                "deployment.tool-absent",
                name,
                "declared tool is absent from the supplied complete inventory",
            )
        desired = _expected(tools[name], expected["mapping"], target, config["policy"]["revision"])
        assessment["expected"] = desired
        if route is None:
            if assessment["route_presence"] == "absent_from_complete_gateway":
                finding(
                    "deployment.route-missing",
                    name,
                    "declared tool has no route in the supplied complete gateway",
                )
            continue
        if route["mediation"] != "required":
            finding(
                "deployment.mediation-" + route["mediation"],
                name,
                "route does not declare mandatory policy evaluation",
            )
        for field in ("action", "resource", "approval_context", "policy_revision"):
            if route[field] != desired[field]:
                finding(
                    "deployment.route-mismatch",
                    f"{name}.{field}",
                    f"expected {desired[field]!r}; observed {route[field]!r}",
                )

        def canonical(rows):
            return {json.dumps(row, sort_keys=True) for row in rows}

        wanted, observed = canonical(desired["principals"]), canonical(route["principals"])
        if observed - wanted:
            finding(
                "deployment.principal-widened",
                name,
                "route includes identities outside the explicitly mapped principal class",
            )
        if wanted - observed:
            finding(
                "deployment.principal-narrowed",
                name,
                "route omits identities from the explicitly mapped principal class",
            )
    return {
        "schema": RESULT_SCHEMA,
        "scope": (
            "supplied configuration and exact policy bytes; not authenticated live enforcement"
        ),
        "status": "configuration_drift_or_unresolved"
        if findings
        else "consistent_with_declared_configuration",
        "configuration_consistent": not findings,
        "runtime_continuity": "not_assessed",
        "native_validation": "not_run",
        "environment": config["environment"],
        "gateway": config["gateway"]["id"],
        "as_of": as_of,
        "snapshot_current": current,
        "inputs": {
            "manifest_sha256": hashlib.sha256(manifest_content).hexdigest(),
            "configuration_sha256": hashlib.sha256(config_content).hexdigest(),
            "materials": {
                name: hashlib.sha256(content).hexdigest()
                for name, content in sorted(materials.items())
            },
        },
        "export": {
            "target": target,
            "receipt_matches": receipt == expected,
            "status": expected["status"],
            "losses": expected["losses"],
        },
        "policy": {"revision": config["policy"]["revision"], "artifacts": artifacts},
        "tools": assessments,
        "findings": findings,
        "authority": analyse(mandate).as_dict(),
    }


def render(report):
    lines = [
        f"DEPLOYMENT {report['status']}",
        f"SCOPE {report['scope']}",
        f"GATEWAY {report['gateway']} environment={report['environment']} as_of={report['as_of']}",
        f"POLICY {report['policy']['revision']} target={report['export']['target']}",
    ]
    lines.extend(
        f"ARTIFACT {row['artifact']}: {row['status']}" for row in report["policy"]["artifacts"]
    )
    lines.extend(
        f"FINDING {row['code']} {row['subject']}: {row['detail']}" for row in report["findings"]
    )
    lines.append("Runtime continuity: not assessed. Native validation: not run.")
    lines.append("AUTHORITY " + json.dumps(report["authority"], sort_keys=True))
    return "\n".join(lines) + "\n"
