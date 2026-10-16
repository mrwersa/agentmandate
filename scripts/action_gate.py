#!/usr/bin/env python3
"""Run the checks a pull request can answer, and report them where they land.

This is the body of the GitHub Action. It exists because the difference
between a tool people try and a tool people run is usually a wrapper, and the
gate was six commands and a handful of flags.

Three deliberate choices.

It runs only the checks the caller supplied inputs for. A manifest is always
enough for `lint` and `reach`; `drift`, `diff`, and `verify` each need
something else and stay off until it is given. An action that demanded a
baseline manifest, agent source, and an OTLP export before it would say
anything would be adopted by nobody.

It writes SARIF but does not upload it. Uploading needs `security-events:
write`, and an action that asks for a token permission it could avoid is one
more reason for a security team to say no. The path is an output and the
upload is the caller's step, which they can read.

And `fail-on: never` exists so a team can turn this on over an existing
repository without blocking everyone on the first day. A gate nobody can
adopt incrementally is a gate that gets removed rather than fixed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.parse import quote

from agentmandate import __version__
from agentmandate._change_review import render as render_review

STEP_SUMMARY = os.environ.get("GITHUB_STEP_SUMMARY")
STEP_OUTPUT = os.environ.get("GITHUB_OUTPUT")
WORKSPACE = Path(os.environ.get("GITHUB_WORKSPACE", "."))
# Artefacts go to the runner's temp directory, not the checkout. A repository
# that fails on a dirty tree, or a later step that archives or commits the
# workspace, would otherwise pick these up, and two jobs writing the same
# filename would collide. Both paths are returned as outputs, so nothing has
# to guess where they went.
ARTEFACTS = Path(os.environ.get("RUNNER_TEMP") or WORKSPACE)


def run(args: list[str]) -> tuple[int, str]:
    """Invoke the CLI through this interpreter.

    Not `mandate` on PATH. The action installs a specific version and must
    analyse with that one; resolving a name on PATH would silently use another
    install if the runner happened to have one.
    """
    result = subprocess.run(
        [sys.executable, "-m", "agentmandate.cli", *args],
        capture_output=True,
        text=True,
        cwd=WORKSPACE,
    )
    return result.returncode, (result.stdout or result.stderr)


def run_json(args: list[str]) -> tuple[int, object]:
    code, out = run([*args, "--json"])
    try:
        return code, json.loads(out)
    except json.JSONDecodeError:
        # A usage error prints prose, not JSON. Carrying the text through
        # rather than crashing keeps the failure legible in the summary.
        return code, {"error": out.strip()}


def detail_for(check: dict, args: list[str]) -> None:
    """Fetch the human-readable output, but only when something will show it.

    Each check runs the CLI twice: once for JSON the script reads, once for
    the text a reviewer reads. Rendering the text from the JSON instead would
    mean a second copy of the formatting, drifting from the one users see. So
    the second call stays, and a clean check simply does not make it.
    """
    if check["ok"] and not check.get("notes"):
        check["detail"] = ""
        return
    check["detail"] = run(args)[1].strip()


def emit(name: str, value: str) -> None:
    if STEP_OUTPUT:
        with open(STEP_OUTPUT, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def count(payload: object, key: str) -> int:
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return len(payload[key])
    return 0


def by_severity(payload: object) -> tuple[int, int]:
    """Split lint findings into the blocking ones and the advisory ones.

    `lint` exits non-zero on an error and zero on a warning, so counting both
    into one number produced a report claiming no finding while the finding
    count sat above zero. Silencing the warning would have made the arithmetic
    agree by losing a real finding, which is the failure this whole package
    exists to catch. So they are counted apart and both are shown.
    """
    findings = payload.get("findings", []) if isinstance(payload, dict) else []
    if not isinstance(findings, list):
        return 0, 0
    blocking = sum(1 for f in findings if isinstance(f, dict) and f.get("severity") != "warning")
    return blocking, len(findings) - blocking


def _git(*args: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-replace-objects", *args],
        cwd=WORKSPACE,
        capture_output=True,
    )
    if result.returncode:
        raise ValueError(
            "cannot read configured Git ref: "
            + result.stderr.decode("utf-8", errors="replace").strip()
        )
    return result.stdout


def _git_blob(commit: str, path: str) -> bytes:
    normalized = PurePosixPath(path)
    if (
        not path
        or normalized.is_absolute()
        or normalized.as_posix() != path
        or ".." in normalized.parts
        or "\\" in path
        or any(c in path for c in "\r\n\x00")
    ):
        raise ValueError("material paths must be canonical relative Git paths")
    entries = _git("--literal-pathspecs", "ls-tree", "-z", commit, "--", path).split(b"\0")
    entries = [entry for entry in entries if entry]
    if len(entries) != 1:
        raise ValueError(f"selected Git ref has no regular file at {path!r}")
    metadata, name = entries[0].split(b"\t", 1)
    mode, kind, oid = metadata.split()
    if name != path.encode() or kind != b"blob" or mode not in (b"100644", b"100755"):
        raise ValueError(f"selected Git ref path {path!r} is not a regular file")
    return _git("cat-file", "blob", oid.decode("ascii"))


def _commit(ref: str) -> str:
    commit = _git("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    commit = commit.decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("Git ref did not resolve to a commit digest")
    return commit


def _review_check(baseline: str, manifest: str, depth: str, workflows: str = "") -> dict:
    try:
        ref = os.environ.get("INPUT_REVIEW_REF", "").strip()
        decision = os.environ.get("INPUT_REVIEW_DECISION", "").strip()
        as_of = os.environ.get("INPUT_REVIEW_AS_OF", "").strip()
        if not baseline or not ref or not decision or not as_of:
            raise ValueError("review needs baseline, review-ref, review-decision and review-as-of")
        commit = _commit(ref)
        mappings = {}
        for line in os.environ.get("INPUT_REVIEW_SOURCES", "").splitlines():
            if not line.strip():
                continue
            locator, separator, path = line.strip().partition("=")
            if not separator or not locator or not path or locator in mappings:
                raise ValueError("review-sources needs unique LOCATOR=GIT_PATH mappings")
            mappings[locator] = path
        with TemporaryDirectory(prefix="agentmandate-review-", dir=ARTEFACTS) as temporary:
            directory = Path(temporary)
            record = directory / "decision.json"
            record.write_bytes(_git_blob(commit, decision))
            args = [
                "review",
                baseline,
                manifest,
                "--depth",
                depth,
                "--decision",
                str(record),
                "--as-of",
                as_of,
            ]
            if workflows:
                args.extend(["--required-workflows", workflows])
            for index, (locator, path) in enumerate(mappings.items()):
                capture = directory / f"source-{index}"
                capture.write_bytes(_git_blob(commit, path))
                args.extend(["--source", f"{locator}={capture}"])
            code, result = run_json(args)
        detail = (
            render_review(result)
            if isinstance(result, dict) and "schema" in result
            else str(result)
        )
        return {
            "name": "review",
            "ok": code == 0,
            "findings": max(int(code != 0), count(result, "findings")),
            "exit": code,
            "detail": detail,
            "result": result,
            "selection": {"ref": ref, "commit": commit, "decision": decision, "sources": mappings},
        }
    except (OSError, ValueError, UnicodeError) as exc:
        return {
            "name": "review",
            "ok": False,
            "findings": 1,
            "exit": 2,
            "detail": str(exc),
            "result": {"error": str(exc)},
        }


def _diff_check(baseline: str, manifest: str, depth: str, workflows: str = "") -> dict:
    args = ["diff", baseline, manifest, "--depth", depth]
    if workflows:
        args.extend(["--required-workflows", workflows])
    code, delta = run_json(args)
    widening = [row for row in delta.get("changes", []) if row.get("direction") == "widening"]
    regressed = [row for row in delta.get("required_workflows", [])
                 if row["relation"] == "regressed"]
    check = {
        "name": "diff", "ok": code == 0, "exit": code, "result": delta,
        "findings": max(int(code != 0), len(widening) + len(regressed)),
        "widening_findings": len(widening), "workflow_regressions": len(regressed),
    }
    detail_for(check, args)
    return check


def _release_checks(baseline: str, manifest: str, depth: str) -> list[dict]:
    path = os.environ.get("INPUT_REQUIRED_WORKFLOWS", "").strip()
    ref = os.environ.get("INPUT_REQUIRED_WORKFLOWS_REF", "").strip()
    review_configured = any(
        os.environ.get(f"INPUT_REVIEW_{name}", "").strip()
        for name in ("REF", "DECISION", "SOURCES", "AS_OF")
    )
    try:
        with TemporaryDirectory(prefix="agentmandate-workflows-", dir=ARTEFACTS) as temporary:
            workflows = ""
            selection = None
            if path or ref:
                if not baseline or not path or not ref:
                    raise ValueError(
                        "required workflows need baseline, required-workflows and "
                        "required-workflows-ref"
                    )
                commit = _commit(ref)
                content = _git_blob(commit, path)
                workflows = str(Path(temporary) / "required.json")
                Path(workflows).write_bytes(content)
                selection = {
                    "ref": ref, "commit": commit, "path": path,
                    "source_sha256": hashlib.sha256(content).hexdigest(),
                }
            checks = []
            diff = _diff_check(baseline, manifest, depth, workflows) if baseline else None
            if diff is not None:
                if selection is not None:
                    diff["workflow_selection"] = selection
                checks.append(diff)
            if review_configured:
                review = _review_check(baseline, manifest, depth, workflows)
                checks.append(review)
                if review["ok"] and diff is not None and not diff["ok"]:
                    result = review["result"]
                    if (
                        result.get("status") == "eligible_recorded_acceptance"
                        and result.get("gate_satisfied") is True
                        and result.get("comparison") == diff["result"]
                        and not diff["workflow_regressions"]
                    ):
                        diff["blocking_findings"] = 0
                        diff["blocks_gate"] = False
                        diff["accepted_widenings"] = diff["widening_findings"]
                    else:
                        review["ok"] = False
                        review["findings"] += 1
                        review["detail"] += "\nAction diff and review comparison do not match."
            return checks
    except (OSError, ValueError, UnicodeError) as exc:
        # Keep the ordinary authority comparison visible when annotation selection fails.
        checks = [_diff_check(baseline, manifest, depth)] if baseline else []
        checks.append({
            "name": "required-workflows", "ok": False, "exit": 2, "findings": 1,
            "detail": str(exc), "result": {"error": str(exc)},
        })
        return checks


def _workflow_sarif(log: dict, checks: list[dict], manifest: str) -> dict:
    results = []
    rules = {
        "workflow.regressed": "A required workflow no longer conforms in this release.",
        "workflow.invalid": "Required workflows could not be selected or checked.",
    }
    for check in checks:
        if check["name"] == "required-workflows" or (
            check["name"] == "diff" and check.get("workflow_selection") and check["exit"] == 2
        ):
            results.append({
                "ruleId": "workflow.invalid", "level": "error",
                "message": {"text": check["detail"]},
            })
        if check["name"] != "diff":
            continue
        delta = check["result"]
        for row in delta.get("required_workflows", []):
            if row["relation"] != "regressed":
                continue
            failure = row["failure"]
            results.append({
                "ruleId": "workflow.regressed", "level": "error",
                "message": {"text": f"{row['name']}: step {failure['step']} "
                            f"{failure['rule']}: {failure['detail']}"},
                "properties": {"workflow": row["name"], "failure": failure,
                               "inputs": delta["required_workflows_metadata"]},
            })
    if results:
        uri = (Path(manifest).as_uri() if Path(manifest).is_absolute()
               else quote(Path(manifest).as_posix(), safe="/"))
        for result in results:
            result["locations"] = [{"physicalLocation": {"artifactLocation": {"uri": uri}}}]
        log["runs"].append({
            "tool": {"driver": {"name": "AgentMandate workflows", "version": __version__,
                               "rules": [{"id": key, "shortDescription": {"text": text}}
                                         for key, text in rules.items()]}},
            "results": results,
        })
    return log


def main() -> int:
    manifest = os.environ["INPUT_MANIFEST"]
    depth = os.environ.get("INPUT_DEPTH", "8")
    checks: list[dict] = []

    code, payload = run_json(["lint", manifest])
    blocking, advisory = by_severity(payload)
    check = {"name": "lint", "ok": code == 0,
             "findings": max(int(code != 0), blocking), "notes": advisory}
    detail_for(check, ["lint", manifest])
    checks.append(check)

    args = ["reach", manifest, "--depth", depth]
    code, reach = run_json(args)
    check = {"name": "reach", "ok": code == 0,
             "findings": max(int(code != 0), count(reach, "breaches"))}
    detail_for(check, args)
    checks.append(check)

    source = os.environ.get("INPUT_SOURCE", "").strip()
    if source:
        args = ["drift", manifest, "--source", source]
        code, drift = run_json(args)
        check = {"name": "drift", "ok": code == 0,
                 "findings": max(int(code != 0), count(drift, "findings"))}
        detail_for(check, args)
        checks.append(check)

    baseline = os.environ.get("INPUT_BASELINE", "").strip()
    checks.extend(_release_checks(baseline, manifest, depth))

    traces = os.environ.get("INPUT_TRACES", "").strip()
    if traces:
        args = ["verify", manifest, "--otel", traces]
        for line in os.environ.get("INPUT_MAP", "").splitlines():
            if line.strip():
                args += ["--map", line.strip()]
        code, report = run_json(args)
        conformance = report.get("conformance", {}) if isinstance(report, dict) else {}
        check = {
            "name": "verify",
            "ok": code == 0,
            "findings": max(int(code != 0), count(conformance, "violations")),
        }
        detail_for(check, args)
        checks.append(check)

    total = sum(check.get("blocking_findings", check["findings"]) for check in checks)
    advisory_total = sum(check.get("notes", 0) for check in checks)
    verdict = "findings" if any(c.get("blocks_gate", not c["ok"]) for c in checks) else "clean"

    report_path = ARTEFACTS / "agentmandate-report.json"
    report_path.write_text(
        json.dumps(
            {
                "verdict": verdict,
                "findings": total,
                "notes": advisory_total,
                "checks": checks,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    sarif_path = ""
    if os.environ.get("INPUT_SARIF", "true").lower() == "true":
        code, sarif = run(["reach", manifest, "--depth", depth, "--sarif"])
        target = ARTEFACTS / "agentmandate.sarif"
        if code in (0, 1) and any(
            check["name"] in {"diff", "required-workflows"} for check in checks
        ):
            sarif = json.dumps(_workflow_sarif(json.loads(sarif), checks, manifest), indent=2)
        target.write_text(sarif, encoding="utf-8")
        sarif_path = str(target)

    if os.environ.get("INPUT_SUMMARY", "true").lower() == "true" and STEP_SUMMARY:
        _, graph = run(["reach", manifest, "--depth", depth, "--graph"])
        # Only the summary shows it, so it is fetched only when written.
        with open(STEP_SUMMARY, "a", encoding="utf-8") as handle:
            handle.write(summary(checks, verdict, total, advisory_total, graph))

    emit("verdict", verdict)
    emit("findings", str(total))
    emit("notes", str(advisory_total))
    emit("sarif-file", sarif_path)
    emit("report", str(report_path))

    print(
        f"{len(checks)} check(s), {total} finding(s), {advisory_total} note(s), verdict {verdict}"
    )
    for check in checks:
        mark = (
            "RECORDED ACCEPTANCE"
            if check.get("accepted_widenings")
            else ("PASS" if check["ok"] else "FAIL")
        )
        trailer = f"  ({check['notes']} note(s))" if check.get("notes") else ""
        print(f"  {mark}  {check['name']}{trailer}")

    if verdict == "clean":
        return 0
    if os.environ.get("INPUT_FAIL_ON", "findings").lower() == "never":
        print("fail-on=never, so the findings above do not fail this step")
        return 0
    return 1


def summary(checks: list[dict], verdict: str, total: int, advisory: int, graph: str) -> str:
    """Build the job summary, with the graph GitHub renders inline."""
    accepted = sum(c.get("accepted_widenings", 0) for c in checks)
    head = "No finding" if verdict == "clean" else f"{total} finding(s)"
    if accepted:
        head = (
            f"{total} blocking finding(s); {accepted} widening change(s) with recorded acceptance"
        )
    if advisory:
        head += f", {advisory} note(s)"
    lines = [
        "## AgentMandate",
        "",
        f"**{head}** across {len(checks)} check(s).",
        "",
        "| | check | question |",
        "|---|---|---|",
    ]
    questions = {
        "lint": "Is any single tool declared wrongly?",
        "reach": "Can permitted calls combine into a breach?",
        "drift": "Does the manifest still describe the code?",
        "diff": "Did authority widen or a required workflow regress?",
        "required-workflows": "Could the pinned workflow annotation be selected?",
        "review": "Is the recorded acceptance eligible for this exact diff?",
        "verify": "Did the recorded run stay inside the mandate?",
    }
    for check in checks:
        # A check that passed while raising something advisory is neither a
        # tick nor a cross. Showing it as a tick is what let a real warning
        # disappear from this table.
        mark = (
            "📝"
            if check.get("accepted_widenings")
            else ("❌" if not check["ok"] else ("⚠️" if check.get("notes") else "✅"))
        )
        lines.append(f"| {mark} | `{check['name']}` | {questions.get(check['name'], '')} |")

    for check in checks:
        selection = check.get("workflow_selection")
        if selection is None:
            continue
        metadata = check["result"].get("required_workflows_metadata", {})
        lines += ["", "### Required workflows (pinned input)", "", "```",
                  f"commit: {selection['commit']}", f"path: {selection['path']}",
                  f"source_sha256: {selection['source_sha256']}",
                  f"manifest_sha256: {metadata.get('manifest_sha256', 'unresolved')}"]
        lines.extend(
            f"{row['name']}: {row['relation']}" + (
                f"; step {row['failure']['step']} {row['failure']['rule']}: "
                f"{row['failure']['detail']}" if row['failure'] is not None else ""
            ) for row in check["result"].get("required_workflows", [])
        )
        lines += ["```", ""]

    failing = [check for check in checks if not check["ok"]]
    if failing:
        lines += ["", "### What was found", ""]
        for check in failing:
            lines += [f"**`{check['name']}`**", "", "```", check["detail"], "```", ""]

    reviewed = [c for c in checks if c["name"] == "review" and c["ok"]]
    for check in reviewed:
        lines += [
            "",
            "### Recorded review (not deployment approval)",
            "",
            "```",
            check["detail"],
            "```",
            "",
        ]

    noted = [c for c in checks if c["ok"] and c.get("notes")]
    if noted:
        lines += [
            "",
            "### Advisory, not blocking",
            "",
            "These do not fail the gate. They are here because a report that "
            "says nothing was found, while something was, is the failure this "
            "package is about.",
            "",
        ]
        for check in noted:
            lines += [f"**`{check['name']}`**", "", "```", check["detail"], "```", ""]

    if graph.strip().startswith("flowchart"):
        lines += [
            "### Authority graph",
            "",
            "```mermaid",
            graph.strip(),
            "```",
            "",
        ]

    lines.append(
        "_Findings describe what the reviewed manifest **permits** under a "
        "bounded search, not what the model tends to do._"
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
