"""Join captured OPA decisions to explicitly mapped OTLP tool attempts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from ._deployment_drift import _coverage, _date, _read, evaluate
from ._policy_export import object_fields, pairs, string
from .manifest import SCHEMA_VERSION
from .otel import OP_ATTR, TOOL_NAME_ATTR, TOOL_OP

RECONCILE_VERSION = 1
RESULT_SCHEMA = "agentmandate.deployment-reconcile/v1"
JOIN_FIELDS = (
    "decision_id",
    "invocation_id",
    "run_id",
    "manifest_sha256",
    "configuration_sha256",
    "manifest_version",
    "gateway",
    "policy_revision",
    "principal",
    "action",
    "resource",
    "approved",
    "effect_applied",
)


def _mapping(content):
    value = object_fields(
        json.loads(content, object_pairs_hook=pairs),
        {
            "reconcile_version",
            "bundle",
            "input_key",
            "attributes",
            "coverage",
            "observed_at",
            "expires",
            "pins",
        },
        "reconciliation mapping",
    )
    if type(value["reconcile_version"]) is not int or value["reconcile_version"] != 1:
        raise ValueError("unsupported reconcile_version")
    string(value["bundle"])
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", string(value["input_key"])):
        raise ValueError("input_key must be an application object identifier")
    attributes = object_fields(value["attributes"], JOIN_FIELDS, "telemetry attributes")
    for field in attributes.values():
        string(field)
    if len(set(attributes.values())) != len(attributes):
        raise ValueError("telemetry attributes must be distinct")
    coverage = object_fields(value["coverage"], {"decisions", "telemetry"}, "capture coverage")
    for field in coverage.values():
        _coverage(field)
    if _date(value["observed_at"]) > _date(value["expires"]):
        raise ValueError("capture expiry precedes observation date")
    pins = object_fields(
        value["pins"], {"manifest", "configuration", "decisions", "telemetry"}, "capture pins"
    )
    for digest in pins.values():
        if not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest):
            raise ValueError("capture pins must be lowercase SHA-256 digests")
    return value


def _any_value(value):
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("OTLP attributes require one AnyValue variant")
    key, raw = next(iter(value.items()))
    if key == "stringValue" and isinstance(raw, str):
        return raw
    if key == "boolValue" and type(raw) is bool:
        return raw
    if key == "intValue" and type(raw) in (str, int) and re.fullmatch(r"-?\d+", str(raw)):
        return int(raw)
    # Unsupported variants stay unknown; they never become truthy approval.
    return None


def _spans(content):
    try:
        documents = [json.loads(content, object_pairs_hook=pairs)]
    except json.JSONDecodeError:
        documents = [
            json.loads(line, object_pairs_hook=pairs)
            for line in content.splitlines()
            if line.strip()
        ]
    if not documents:
        raise ValueError("telemetry capture is empty")
    result = []
    for document in documents:
        if not isinstance(document, dict) or not isinstance(document.get("resourceSpans"), list):
            raise ValueError("telemetry must contain OTLP resourceSpans")
        for resource in document["resourceSpans"]:
            if not isinstance(resource, dict) or not isinstance(
                resource.get("scopeSpans", []), list
            ):
                raise ValueError("OTLP resource must contain a scopeSpans array")
            for scope in resource.get("scopeSpans", []):
                if not isinstance(scope, dict) or not isinstance(scope.get("spans", []), list):
                    raise ValueError("OTLP scope must contain a spans array")
                for span in scope.get("spans", []):
                    if not isinstance(span, dict) or not isinstance(
                        span.get("attributes", []), list
                    ):
                        raise ValueError("OTLP span must contain an attributes array")
                    attributes = {}
                    for attribute in span.get("attributes", []):
                        if not isinstance(attribute, dict) or not isinstance(
                            attribute.get("key"), str
                        ):
                            raise ValueError("OTLP attribute must name a key")
                        if attribute["key"] in attributes:
                            raise ValueError("duplicate OTLP attribute key")
                        attributes[attribute["key"]] = _any_value(attribute.get("value"))
                    result.append(attributes)
    return result


def _expected(request, tools):
    """Only the generated stateless exporter subset, not an arbitrary Rego evaluator."""
    if not isinstance(request, dict) or not isinstance(request.get("context"), dict):
        return False
    return any(
        type(request.get("principal")) is str
        and request["principal"] in row["expected"]["principals"]
        and request.get("action") == row["expected"]["action"]
        and request.get("resource") == row["expected"]["resource"]
        and (
            row["expected"]["approval_context"] is None
            or request["context"].get(row["expected"]["approval_context"]) is True
        )
        for row in tools
        if row["expected"] is not None
    )


def reconcile(
    manifest_content: bytes,
    config_content: bytes,
    decisions_content: bytes,
    telemetry_content: bytes,
    mapping_content: bytes,
    *,
    root: Path,
    as_of: str,
):
    mapping = _mapping(mapping_content)
    baseline = evaluate(manifest_content, config_content, root=root, as_of=as_of)
    if baseline["export"]["target"] != "rego":
        raise ValueError("deployment reconciliation currently supports Rego/OPA only")
    config = json.loads(config_content, object_pairs_hook=pairs)
    locator = config["export"]["mapping"]
    export_content = _read(root.resolve(), locator)
    if hashlib.sha256(export_content).hexdigest() != baseline["inputs"]["materials"][locator]:
        raise ValueError("export mapping changed during reconciliation")
    policy_path = json.loads(export_content)["package"].replace(".", "/") + "/allow"
    records = json.loads(decisions_content, object_pairs_hook=pairs)
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise ValueError("OPA decision capture must be a JSON array of event objects")
    spans = _spans(telemetry_content)
    findings = list(baseline["findings"])

    def finding(code, subject, detail):
        findings.append({"code": "reconciliation." + code, "subject": subject, "detail": detail})

    inputs = {
        "manifest": manifest_content,
        "configuration": config_content,
        "decisions": decisions_content,
        "telemetry": telemetry_content,
        "mapping": mapping_content,
    }
    digests = {name: hashlib.sha256(content).hexdigest() for name, content in inputs.items()}
    trusted = True
    for name, digest in mapping["pins"].items():
        if digest != digests[name]:
            finding("source-mismatch", name, "capture pin differs from supplied bytes")
            trusted = False
    current = (
        _date(mapping["observed_at"]) <= _date(as_of) <= _date(mapping["expires"])
        and baseline["snapshot_current"]
    )
    if not current:
        finding("capture-not-current", "captures", "capture/configuration window is not current")
    trusted = trusted and current
    for name, coverage in mapping["coverage"].items():
        if coverage != "complete":
            finding("coverage-incomplete", name, "capture membership is not declared complete")

    counts = Counter(r.get("decision_id") for r in records if isinstance(r.get("decision_id"), str))
    decisions = {}
    decision_rows = []
    ignored = 0
    for position, record in enumerate(records):
        identifier = record.get("decision_id")
        if record.get("path") not in (policy_path, "/" + policy_path):
            ignored += 1
            if not isinstance(record.get("path"), str):
                finding("decision-path-unresolved", str(position), "event has no policy path")
            continue
        row = {
            "index": position,
            "decision_id": identifier if isinstance(identifier, str) else None,
            "expected_export_result": None,
            "observed_result": None,
            "eligible": False,
        }
        decision_rows.append(row)
        if not isinstance(identifier, str) or not identifier:
            finding("decision-id-unresolved", str(position), "event has no decision identifier")
            continue
        if counts[identifier] != 1:
            finding(
                "decision-ambiguous", identifier, "decision identifier is repeated in the capture"
            )
            continue
        mask = []
        for field in ("erased", "masked"):
            pointers = record.get(field, [])
            if not isinstance(pointers, list) or not all(
                isinstance(p, str) and (p == "" or p.startswith("/")) for p in pointers
            ):
                raise ValueError("OPA masking metadata must be arrays of JSON pointers")
            mask.extend(pointers)
        protected = (
            "/decision_id",
            "/path",
            "/bundles",
            "/result",
            "/input/principal",
            "/input/action",
            "/input/resource",
            "/input/context",
            "/input/" + mapping["input_key"],
        )
        masked = any(
            p == target or p.startswith(target + "/") or target.startswith(p + "/")
            for p in mask
            for target in protected
        )
        request = record.get("input")
        correlation = request.get(mapping["input_key"]) if isinstance(request, dict) else None
        bundles = record.get("bundles")
        bundle = bundles.get(mapping["bundle"]) if isinstance(bundles, dict) else None
        if not trusted or masked or type(record.get("result")) is not bool:
            finding(
                "decision-untrusted", identifier, "current exact unmasked Boolean decision required"
            )
            continue
        if not isinstance(correlation, dict) or not isinstance(bundle, dict):
            finding(
                "decision-join-unresolved",
                identifier,
                "application correlation or bundle metadata absent",
            )
            continue
        expected_join = {
            "manifest_sha256": digests["manifest"],
            "configuration_sha256": digests["configuration"],
            "manifest_version": SCHEMA_VERSION,
            "gateway": baseline["gateway"],
        }
        valid = True
        for field, expected in expected_join.items():
            if correlation.get(field) != expected or type(correlation.get(field)) is not type(
                expected
            ):
                finding(
                    "decision-join-mismatch",
                    f"{identifier}.{field}",
                    "decision join differs from deployment",
                )
                valid = False
        if bundle.get("revision") != baseline["policy"]["revision"]:
            finding(
                "decision-revision-mismatch",
                identifier,
                "bundle revision differs from configuration",
            )
            valid = False
        for field in ("run_id", "invocation_id"):
            if not isinstance(correlation.get(field), str) or not correlation[field]:
                finding(
                    "decision-join-unresolved",
                    f"{identifier}.{field}",
                    "application identifier absent",
                )
                valid = False
        if not valid:
            continue
        expected = _expected(request, baseline["tools"])
        row.update(eligible=True, expected_export_result=expected, observed_result=record["result"])
        if expected is not record["result"]:
            finding(
                "decision-contradiction",
                identifier,
                "recorded decision differs from exported stateless subset",
            )
        decisions[identifier] = (record, correlation)

    attempts = []
    for position, attributes in enumerate(spans):
        if attributes.get(OP_ATTR) != TOOL_OP:
            continue
        name = attributes.get(TOOL_NAME_ATTR)
        if not isinstance(name, str) or not name:
            raise ValueError("execute_tool span must name a tool")
        fields = {
            field: attributes.get(attribute) for field, attribute in mapping["attributes"].items()
        }
        attempts.append({"index": position, "tool": name, "fields": fields})
    span_decisions = Counter(
        a["fields"]["decision_id"] for a in attempts if isinstance(a["fields"]["decision_id"], str)
    )
    invocations = Counter(
        (a["fields"]["run_id"], a["fields"]["invocation_id"])
        for a in attempts
        if all(isinstance(a["fields"][f], str) for f in ("run_id", "invocation_id"))
    )
    tools = {r["tool"]: r["expected"] for r in baseline["tools"] if r["expected"] is not None}
    assessments = []
    used = set()
    for attempt in attempts:
        fields = attempt["fields"]
        identifier = fields["decision_id"]
        subject = "span:" + str(attempt["index"])
        row = {
            "index": attempt["index"],
            "tool": attempt["tool"],
            "decision_id": identifier,
            "join": "unresolved",
            "reported_effect_applied": None,
        }
        assessments.append(row)
        valid = trusted
        for field, value in fields.items():
            expected_type = (
                bool
                if field in ("approved", "effect_applied")
                else int
                if field == "manifest_version"
                else str
            )
            if type(value) is not expected_type or (expected_type is str and not value):
                finding(
                    "span-field-unresolved",
                    f"{subject}.{field}",
                    "mapped typed application attribute absent",
                )
                valid = False
        if not valid:
            continue
        if (
            span_decisions[identifier] != 1
            or invocations[(fields["run_id"], fields["invocation_id"])] != 1
        ):
            finding(
                "span-ambiguous",
                subject,
                "decision or run/invocation identifier is shared by multiple tool spans",
            )
            continue
        if identifier not in decisions:
            missing = (
                mapping["coverage"]["decisions"] == "complete"
                and current
                and counts[identifier] == 0
            )
            finding(
                "decision-missing" if missing else "decision-unresolved",
                subject,
                "no eligible matching decision in the supplied capture",
            )
            continue
        record, correlation = decisions[identifier]
        desired = tools.get(attempt["tool"])
        if desired is None:
            finding("tool-undeclared", subject, "tool span names a tool outside the manifest")
            continue
        wanted = {
            **correlation,
            "decision_id": identifier,
            "policy_revision": baseline["policy"]["revision"],
            "principal": record["input"].get("principal"),
            "action": record["input"].get("action"),
            "resource": record["input"].get("resource"),
        }
        for field in JOIN_FIELDS:
            if field in ("effect_applied", "approved"):
                continue
            if fields[field] != wanted.get(field) or type(fields[field]) is not type(
                wanted.get(field)
            ):
                finding(
                    "span-join-mismatch",
                    f"{subject}.{field}",
                    "tool span differs from its decision join",
                )
                valid = False
        request = record["input"]
        if (
            request.get("action") != desired["action"]
            or request.get("resource") != desired["resource"]
        ):
            finding(
                "span-request-mismatch",
                subject,
                "decision action/resource differs from mapped tool",
            )
            valid = False
        approval = desired["approval_context"]
        if approval is not None and (
            not isinstance(request.get("context"), dict)
            or type(request["context"].get(approval)) is not bool
            or fields["approved"] is not request["context"][approval]
        ):
            finding(
                "span-approval-mismatch",
                subject,
                "tool approval differs from recorded policy input",
            )
            valid = False
        if not valid:
            continue
        used.add(identifier)
        row.update(
            join="matched_within_captured_scope", reported_effect_applied=fields["effect_applied"]
        )
        if record["result"] is False and fields["effect_applied"]:
            finding(
                "denied-effect-observed",
                subject,
                "reported effect is associated with a denied decision; "
                "causal order not established",
            )
    for identifier in sorted(decisions.keys() - used):
        missing = (
            mapping["coverage"]["telemetry"] == "complete"
            and current
            and span_decisions[identifier] == 0
        )
        finding(
            "span-missing" if missing else "span-unresolved",
            identifier,
            "no fully joined tool attempt in the supplied telemetry",
        )
    if not attempts or not decision_rows:
        finding(
            "capture-empty", "captures", "nonempty selected decisions and tool attempts required"
        )
    return {
        "schema": RESULT_SCHEMA,
        "scope": (
            "captured identifiers and exported stateless decisions; "
            "not authenticated live enforcement"
        ),
        "status": "findings_or_unresolved" if findings else "consistent_with_captured_join",
        "inputs": digests,
        "capture_current": current,
        "coverage": mapping["coverage"],
        "ordering": "not_assessed",
        "runtime_continuity": "not_assessed",
        "accounting": "not_assessed",
        "native_validation": "not_run",
        "summary": {
            "decision_events": len(records),
            "selected_decisions": len(decision_rows),
            "ignored_decisions": ignored,
            "total_spans": len(spans),
            "tool_attempts": len(attempts),
            "matched_attempts": len(used),
        },
        "decisions": decision_rows,
        "attempts": assessments,
        "findings": findings,
        "deployment": baseline,
    }


def render(report):
    lines = [
        f"RECONCILIATION {report['status']}",
        f"SCOPE {report['scope']}",
        "SUMMARY " + json.dumps(report["summary"], sort_keys=True),
    ]
    lines.extend(
        f"ATTEMPT {r['tool']} decision={r['decision_id']} join={r['join']} "
        f"reported_effect_applied={r['reported_effect_applied']}"
        for r in report["attempts"]
    )
    lines.extend(f"FINDING {r['code']} {r['subject']}: {r['detail']}" for r in report["findings"])
    lines.append("Ordering, accounting and runtime continuity: not assessed.")
    lines.append("AUTHORITY " + json.dumps(report["deployment"]["authority"], sort_keys=True))
    return "\n".join(lines) + "\n"
