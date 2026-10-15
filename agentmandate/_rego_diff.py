"""Compare exact captured requests across generated Rego revisions."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ._deployment_drift import _read
from ._deployment_reconcile import reconcile
from ._policy_export import object_fields, pairs
from .diff import compare as compare_authority
from .manifest import loads

CAPTURE_VERSION = 1
RESULT_SCHEMA = "agentmandate.rego-effective-diff/v2"
MATERIALS = ("manifest", "configuration", "decisions", "telemetry", "mapping")
REQUEST_FIELDS = ("principal", "action", "resource", "context")


def _json(content):
    value = json.loads(content, object_pairs_hook=pairs)
    json.dumps(value, allow_nan=False)
    return value


def _number(text):
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("request number exceeds the supported decimal range") from exc
    if not number.is_finite():
        raise ValueError("request number exceeds the supported decimal range")
    return number


def _constant(text):
    raise ValueError(f"non-finite request number: {text}")


def _request_json(value):
    """Encode exact decimal values without float conversion or context rounding."""
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                json.dumps(key) + ":" + _request_json(item) for key, item in sorted(value.items())
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(_request_json(item) for item in value) + "]"
    if isinstance(value, Decimal):
        if not value:
            return "0"
        sign, digits, exponent = value.as_tuple()
        coefficient = "".join(str(digit) for digit in digits)
        significant = coefficient.rstrip("0")
        exponent += len(coefficient) - len(significant)
        # Tuple arithmetic is exact even under a low-precision Decimal context;
        # scientific notation also avoids expanding very large exponents.
        return ("-" if sign else "") + significant + (f"e{exponent}" if exponent else "")
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


def _side(content, root, as_of):
    spec = object_fields(_json(content), {"rego_capture_version", *MATERIALS}, "Rego capture set")
    if type(spec["rego_capture_version"]) is not int or spec["rego_capture_version"] != 1:
        raise ValueError("unsupported rego_capture_version")
    root = root.resolve()
    materials = {name: _read(root, spec[name]) for name in MATERIALS}
    report = reconcile(
        materials["manifest"],
        materials["configuration"],
        materials["decisions"],
        materials["telemetry"],
        materials["mapping"],
        root=root,
        as_of=as_of,
    )
    config = _json(materials["configuration"])
    mapping = _json(materials["mapping"])
    input_key = mapping["input_key"]
    if input_key in REQUEST_FIELDS:
        raise ValueError("application correlation key must not replace a policy request field")
    export_path = config["export"]["mapping"]
    export_content = _read(root, export_path)
    deployment = report["deployment"]
    if hashlib.sha256(export_content).hexdigest() != deployment["inputs"]["materials"][export_path]:
        raise ValueError("export mapping changed during comparison")
    export_mapping = _json(export_content)
    records = json.loads(
        materials["decisions"],
        object_pairs_hook=pairs,
        parse_int=_number,
        parse_float=_number,
        parse_constant=_constant,
    )
    requests = defaultdict(list)
    invalid = []
    for row in report["decisions"]:
        request = records[row["index"]].get("input")
        if (
            not isinstance(request, dict)
            or not all(type(request.get(field)) is str for field in REQUEST_FIELDS[:3])
            or not isinstance(request.get("context"), dict)
        ):
            invalid.append(row["index"])
            continue
        semantic = {key: value for key, value in request.items() if key != input_key}
        encoded = _request_json(semantic)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        # Reconciliation permits unrelated payload masking. Exact full-input
        # comparison does not: even a field unused by the exporter must remain
        # visible before the two captured requests can be called identical.
        visible = row["eligible"] and not any(
            pointer == "" or pointer == "/input" or pointer.startswith("/input/")
            for pointer in records[row["index"]].get("masked", [])
            + records[row["index"]].get("erased", [])
        )
        requests[digest].append({**row, "request_visible": visible})
    policy_path = config["policy"]["files"].get("policy.rego")
    tools = defaultdict(set)
    for attempt in report["attempts"]:
        if attempt["join"] == "matched_within_captured_scope":
            tools[attempt["decision_id"]].add(attempt["tool"])
    return {
        "report": report,
        "manifest": loads(materials["manifest"].decode("utf-8")),
        "requests": requests,
        "invalid": invalid,
        "tools": tools,
        "capture_sha256": hashlib.sha256(content).hexdigest(),
        "policy_sha256": deployment["inputs"]["materials"].get(policy_path),
        "boundary": {
            "agent": config["agent"],
            "identity": config["identity"],
            "environment": deployment["environment"],
            "gateway": deployment["gateway"],
            "bundle": mapping["bundle"],
            "input_key": input_key,
            "query_path": export_mapping["package"].replace(".", "/") + "/allow",
        },
    }


def compare(
    baseline_content: bytes,
    candidate_content: bytes,
    *,
    baseline_root: Path,
    candidate_root: Path,
    as_of: str,
):
    """Preserve both reconciliations; compare only exact eligible unique requests."""
    before = _side(baseline_content, baseline_root, as_of)
    after = _side(candidate_content, candidate_root, as_of)
    sides = {"baseline": before, "candidate": after}
    findings = []

    def finding(code, subject, detail):
        findings.append({"code": "rego." + code, "subject": subject, "detail": detail})

    comparable = True
    for label, side in sides.items():
        if side["report"]["findings"]:
            finding(
                "capture-unresolved", label, "reconciliation findings block decision comparison"
            )
            comparable = False
        for position in side["invalid"]:
            finding("request-unresolved", f"{label}:{position}", "typed policy request required")
            comparable = False
    for field in before["boundary"]:
        if before["boundary"][field] != after["boundary"][field]:
            finding(
                "boundary-mismatch", field, "capture sets describe different comparison boundaries"
            )
            comparable = False
    if (
        before["report"]["deployment"]["policy"]["revision"]
        == after["report"]["deployment"]["policy"]["revision"]
        and all(side["policy_sha256"] is not None for side in sides.values())
        and before["policy_sha256"] != after["policy_sha256"]
    ):
        finding("revision-conflict", "policy", "one revision label names different policy bytes")
        comparable = False

    comparisons = []
    for digest in sorted(before["requests"].keys() | after["requests"].keys()):
        rows = {label: side["requests"].get(digest, []) for label, side in sides.items()}
        row = {
            "request_sha256": digest,
            "baseline_decision_ids": [r["decision_id"] for r in rows["baseline"]],
            "candidate_decision_ids": [r["decision_id"] for r in rows["candidate"]],
            "baseline_result": None,
            "candidate_result": None,
            "relation": "unresolved",
            "tools": {
                label: sorted(
                    {
                        tool
                        for decision in rows[label]
                        for tool in side["tools"].get(decision["decision_id"], ())
                    }
                )
                for label, side in sides.items()
            },
        }
        comparisons.append(row)
        if not all(len(value) == 1 for value in rows.values()):
            finding(
                "request-unmatched-or-ambiguous",
                digest,
                "exactly one captured decision for this request is required on each side",
            )
            continue
        left, right = rows["baseline"][0], rows["candidate"][0]
        if not comparable or not all(
            value["eligible"]
            and value["request_visible"]
            and value["observed_result"] is value["expected_export_result"]
            for value in (left, right)
        ):
            finding("comparison-unresolved", digest, "eligible consistent captures required")
            continue
        b, a = left["observed_result"], right["observed_result"]
        relation = (
            "widens"
            if not b and a
            else "narrows"
            if b and not a
            else "stable_allow"
            if a
            else "stable_deny"
        )
        row.update(
            baseline_result=b, candidate_result=a, relation=relation + "_within_captured_scope"
        )
        if relation == "widens":
            finding(
                "decision-widened", digest, "the exact captured request changes from Deny to Allow"
            )
    delta = None
    if before["manifest"].agent == after["manifest"].agent:
        delta = compare_authority(before["manifest"], after["manifest"])
    else:
        finding(
            "authority-comparison-unresolved", "agent", "cannot diff different agent identities"
        )
    if delta is not None and delta.widened:
        finding("authority-widened", "manifest", "independent manifest authority comparison widens")
    if after["report"]["deployment"]["authority"]["breaches"]:
        finding(
            "authority-breach", "manifest", "candidate manifest retains reachable breach findings"
        )
    return {
        "schema": RESULT_SCHEMA,
        "scope": "exact captured requests against generated stateless Rego; not policy equivalence "
        "or authenticated live enforcement",
        "status": "findings_or_unresolved" if findings else "no_widening_within_captured_scope",
        "as_of": as_of,
        "inputs": {
            label: {"capture_sha256": side["capture_sha256"], **side["report"]["inputs"]}
            for label, side in sides.items()
        },
        "boundary_comparable": comparable,
        "baseline": before["report"],
        "candidate": after["report"],
        "authority_diff": delta.as_dict() if delta is not None else None,
        "comparisons": comparisons,
        "summary": {
            "requests": len(comparisons),
            "compared": sum(r["relation"] != "unresolved" for r in comparisons),
            "widened": sum(r["relation"] == "widens_within_captured_scope" for r in comparisons),
        },
        "ordering": "not_assessed",
        "accounting": "not_assessed",
        "runtime_continuity": "not_assessed",
        "native_validation": "not_run",
        "findings": findings,
    }


def _decision(value):
    return "Allow" if value is True else "Deny" if value is False else "unresolved"


def render(report):
    lines = [f"REGO DIFF {report['status']}", f"SCOPE {report['scope']}"]
    for row in report["comparisons"]:
        lines.append(
            f"REQUEST {row['request_sha256']} {row['relation']} "
            f"baseline={_decision(row['baseline_result'])} "
            f"candidate={_decision(row['candidate_result'])} "
            f"tools={row['tools']} decisions="
            f"{row['baseline_decision_ids']} -> {row['candidate_decision_ids']}"
        )
    for label in ("baseline", "candidate"):
        for row in report[label]["findings"]:
            lines.append(f"{label.upper()} FINDING {row['code']} {row['subject']}: {row['detail']}")
    lines.extend(
        f"FINDING {row['code']} {row['subject']}: {row['detail']}" for row in report["findings"]
    )
    lines.append("AUTHORITY DIFF " + json.dumps(report["authority_diff"], sort_keys=True))
    if report["authority_diff"] is None:
        for label in ("baseline", "candidate"):
            lines.append(
                label.upper()
                + " AUTHORITY "
                + json.dumps(report[label]["deployment"]["authority"], sort_keys=True)
            )
    lines.append(
        "Ordering, accounting and runtime continuity: not assessed. Native validation: not run."
    )
    return "\n".join(lines) + "\n"
