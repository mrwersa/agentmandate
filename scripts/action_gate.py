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
from contextlib import suppress
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile, TemporaryDirectory
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
    install if the runner happened to have one. Isolated mode also excludes
    checkout modules and PYTHONPATH: candidate code must not replace the analyzer.
    """
    result = subprocess.run(
        [sys.executable, "-I", "-m", "agentmandate.cli", *args],
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


def _io_error(errors, label, exc):
    message = f"Cannot write {label}: {exc}"
    errors.append(message)
    print(f"error: {message}", file=sys.stderr)


def _publish(path, content, errors):
    """Replace a report only after a complete write; never follow its symlink."""
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="agentmandate-output-",
            dir=path.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(path)
    except OSError as exc:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink()
        _io_error(errors, path.name, exc)
        return ""
    return str(path)


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
    if not isinstance(delta, dict) or any(
        not isinstance(delta.get(key, []), list)
        or any(not isinstance(row, dict) for row in delta[key])
        for key in ("changes", "required_workflows") if key in delta
    ):
        error = "diff returned an unexpected JSON result shape"
        return {
            "name": "diff", "ok": False, "exit": 2, "result": {"error": error},
            "detail": error, "findings": 1, "widening_findings": 0,
            "workflow_regressions": 0,
        }
    widening = [row for row in delta.get("changes", []) if row.get("direction") == "widening"]
    regressed = [row for row in delta.get("required_workflows", [])
                 if row.get("relation") == "regressed"]
    check = {
        "name": "diff", "ok": code == 0, "exit": code, "result": delta,
        "findings": max(int(code != 0), len(widening) + len(regressed)),
        "widening_findings": len(widening), "workflow_regressions": len(regressed),
    }
    detail_for(check, args)
    return check


def _repair_configuration() -> dict | None:
    enabled = os.environ.get("INPUT_REPAIR_SUGGESTIONS", "false").strip().lower()
    if enabled == "false":
        return None
    repair = {"status": "pending", "scope": "advisory proposals; original gate unchanged"}
    try:
        if enabled != "true":
            raise ValueError("repair-suggestions must be true or false")
        configuration = {}
        for name, default, maximum in (
            ("max-edits", 2, 8), ("max-evaluations", 128, 1024),
            ("max-candidates", 5, 20), ("timeout-seconds", 60, 300),
        ):
            raw = os.environ.get(f"INPUT_REPAIR_{name.upper().replace('-', '_')}", str(default))
            if not re.fullmatch(r"[1-9][0-9]{0,3}", raw) or int(raw) > maximum:
                raise ValueError(f"repair-{name} must be an integer from 1 to {maximum}")
            configuration[name] = int(raw)
        for name in ("keep-tools", "ceiling-grids", "discover-ceilings"):
            configuration[name] = [
                line.strip() for line in os.environ.get(
                    f"INPUT_REPAIR_{name.upper().replace('-', '_')}", "",
                ).splitlines() if line.strip()
            ]
        if configuration["ceiling-grids"] and configuration["discover-ceilings"]:
            raise ValueError("repair-ceiling-grids and repair-discover-ceilings cannot be combined")
        if not os.environ.get("INPUT_BASELINE", "").strip():
            raise ValueError("repair suggestions require baseline")
        repair["configuration"] = configuration
    except ValueError as exc:
        repair.update(status="configuration_error", error=str(exc))
    return repair


def _repair_suggestions(repair, checks, baseline, manifest, depth, workflows):
    if repair is None or repair["status"] != "pending":
        return
    diff = next((c for c in checks if c["name"] == "diff"), None)
    if diff is None or diff["exit"] not in (0, 1) or "error" in diff["result"]:
        repair.update(status="skipped", error="A valid release comparison is unavailable")
        return
    triggers = list(repair.get("trigger_checks", []))
    if diff.get("blocks_gate", not diff["ok"]):
        triggers.append("diff")
    repair["trigger_checks"] = triggers
    if not triggers:
        repair.update(status="not_needed", reason="No blocking manifest or release finding")
        return
    repair["workflow_selection"] = diff.get("workflow_selection")
    config = repair["configuration"]
    args = ["remediate", manifest, "--released", baseline, "--depth", depth, "--pareto", "--json"]
    for option in ("max-edits", "max-evaluations", "max-candidates"):
        args.extend(["--" + option, str(config[option])])
    for key, option in (("keep-tools", "--keep-tool"), ("ceiling-grids", "--ceiling-grid"),
                        ("discover-ceilings", "--discover-ceiling")):
        for value in config[key]:
            args.extend([option, value])
    if workflows:
        args.extend(["--required-workflows", workflows])
    try:
        process = subprocess.run(
            [sys.executable, "-I", "-m", "agentmandate.cli", *args], cwd=WORKSPACE,
            capture_output=True, text=True, timeout=config["timeout-seconds"],
        )
        repair["exit"] = process.returncode
        if process.returncode not in (0, 1):
            raise ValueError((process.stderr or process.stdout).strip() or "Repair process failed")
        result = json.loads(process.stdout)
        expected = {"manifest_sha256": repair["selection"]["manifest"]["sha256"],
                    "released_sha256": repair["selection"]["released"]["sha256"]}
        if (
            not isinstance(result, dict) or result.get("schema") != "agentmandate.remediation/v6"
            or result.get("input") != expected or not isinstance(result.get("candidates"), list)
            or not isinstance(result.get("search"), dict)
            or not isinstance(result.get("discovery", {}), dict)
            or result.get("release", {}).get("comparison") != diff["result"]
        ):
            raise ValueError("Repair result does not match the gate's pinned release comparison")
        if any(
            not isinstance(c, dict) or not isinstance(c.get("authority"), dict)
            or not isinstance(c.get("release"), dict) or c["release"].get("gate_passed") is not True
            or not isinstance(c.get("impact"), dict) or not isinstance(c.get("edits"), list)
            or not isinstance(c.get("manifest"), dict)
            for c in result["candidates"]
        ):
            raise ValueError("Repair result contains an invalid candidate envelope")
        if any(result["search"].get(key.replace("-", "_")) != config[key]
               for key in ("max-edits", "max-evaluations", "max-candidates")):
            raise ValueError("Repair result does not match configured search bounds")
        json.dumps(result, allow_nan=False)
        repair.update(status="completed", result=result)
    except subprocess.TimeoutExpired:
        repair.update(status="timeout", error="Repair time limit reached; no proposals retained")
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError, RecursionError) as exc:
        repair.update(status="error", error=str(exc))


def _release_checks(baseline: str, manifest: str, depth: str, repair=None) -> list[dict]:
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
            _repair_suggestions(repair, checks, baseline, manifest, depth, workflows)
            return checks
    except (OSError, ValueError, UnicodeError) as exc:
        # Keep the ordinary authority comparison visible when annotation selection fails.
        checks = [_diff_check(baseline, manifest, depth)] if baseline else []
        checks.append({
            "name": "required-workflows", "ok": False, "exit": 2, "findings": 1,
            "detail": str(exc), "result": {"error": str(exc)},
        })
        if review_configured:
            error = "Review was not evaluated because required workflows could not be selected: "
            error += str(exc)
            checks.append({
                "name": "review", "ok": False, "exit": 2, "findings": 1, "skipped": True,
                "detail": error, "result": {"error": error},
            })
        if repair is not None and repair["status"] == "pending":
            repair.update(status="skipped", error="Required workflow selection failed: " + str(exc))
        return checks


def _workflow_sarif(log: dict, checks: list[dict], manifest: str) -> bool:
    """Append workflow findings and report whether the log changed."""
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
            if row.get("relation") != "regressed":
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
    return bool(results)


def _source_locations(log, manifest, original):
    def uri(path):
        try:
            return Path(path).resolve().relative_to(WORKSPACE.resolve()).as_posix()
        except ValueError:
            return Path(path).as_posix()

    changed = False
    for run in log["runs"]:
        for result in run.get("results", []):
            for location in result.get("locations", []):
                artifact = location["physicalLocation"]["artifactLocation"]
                if artifact.get("uri") == uri(manifest):
                    artifact["uri"] = uri(original)
                    changed = True
    return changed


def main() -> int:
    manifest = os.environ["INPUT_MANIFEST"]
    baseline = os.environ.get("INPUT_BASELINE", "").strip()
    depth = os.environ.get("INPUT_DEPTH", "8")
    repair = _repair_configuration()
    if repair is None:
        return _gate(manifest, baseline, depth)
    if repair["status"] != "pending":
        return _gate(manifest, baseline, depth, repair)
    try:
        directory = TemporaryDirectory(prefix="agentmandate-analysis-", dir=ARTEFACTS)
    except OSError as exc:
        repair.update(status="error", error="Cannot create analysis snapshot: " + str(exc))
        return _gate(manifest, baseline, depth, repair)
    with directory as temporary:
        original = manifest
        if repair["status"] == "pending":
            try:
                selection = {}
                paths = {}
                for name, path in (("manifest", manifest), ("released", baseline)):
                    source = Path(path) if Path(path).is_absolute() else WORKSPACE / path
                    content = source.read_bytes()
                    snapshot = Path(temporary) / (name + source.suffix)
                    snapshot.write_bytes(content)
                    paths[name] = str(snapshot)
                    selection[name] = {"path": path, "sha256": hashlib.sha256(content).hexdigest()}
                manifest, baseline = paths["manifest"], paths["released"]
                repair["selection"] = selection
            except OSError as exc:
                repair.update(status="error", error="Cannot snapshot manifests: " + str(exc))
        return _gate(manifest, baseline, depth, repair,
                     original if "selection" in repair else None)


def _gate(manifest, baseline, depth, repair=None, original=None) -> int:
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

    if repair is not None:
        repair["trigger_checks"] = [
            c["name"] for c in checks if c["name"] in {"lint", "reach"} and not c["ok"]
        ]
    checks.extend(_release_checks(baseline, manifest, depth, repair))

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
    if repair is not None and "selection" in repair:
        for check in checks:
            check["detail"] = check["detail"].replace(
                manifest, repair["selection"]["manifest"]["path"],
            ).replace(baseline, repair["selection"]["released"]["path"])

    combined = {"verdict": verdict, "findings": total, "notes": advisory_total, "checks": checks}
    repair_path = ""
    if repair is not None:
        combined["repairs"] = repair
        target = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix="agentmandate-repairs-", suffix=".json",
                dir=ARTEFACTS, delete=False,
            ) as handle:
                target = Path(handle.name)
                handle.write(json.dumps(repair, indent=2) + "\n")
            repair_path = str(target)
        except OSError as exc:
            if target is not None:
                with suppress(OSError):
                    target.unlink()
            repair.update(status="error", error="Cannot write repair report: " + str(exc))
    io_errors = []
    report_path = _publish(
        ARTEFACTS / "agentmandate-report.json", json.dumps(combined, indent=2), io_errors,
    )

    sarif_path = ""
    if os.environ.get("INPUT_SARIF", "true").lower() == "true":
        code, sarif = run(["reach", manifest, "--depth", depth, "--sarif"])
        target = ARTEFACTS / "agentmandate.sarif"
        if code in (0, 1):
            log = json.loads(sarif)
            changed = original is not None and _source_locations(log, manifest, original)
            if _workflow_sarif(log, checks, original or manifest) or changed:
                sarif = json.dumps(log, indent=2) + "\n"
        sarif_path = _publish(target, sarif, io_errors)

    if os.environ.get("INPUT_SUMMARY", "true").lower() == "true" and STEP_SUMMARY:
        _, graph = run(["reach", manifest, "--depth", depth, "--graph"])
        # Only the summary shows it, so it is fetched only when written.
        try:
            with open(STEP_SUMMARY, "a", encoding="utf-8") as handle:
                handle.write(summary(checks, verdict, total, advisory_total, graph, repair))
        except OSError as exc:
            _io_error(io_errors, "job summary", exc)

    for name, value in (
        ("verdict", verdict), ("findings", str(total)), ("notes", str(advisory_total)),
        ("sarif-file", sarif_path), ("report", report_path), ("repair-report", repair_path),
    ):
        try:
            emit(name, value)
        except OSError as exc:
            _io_error(io_errors, f"step output {name}", exc)

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
    if repair is not None:
        print(f"  ADVISORY REPAIRS {repair['status']}; original gate unchanged")

    if io_errors:
        return 2
    if verdict == "clean":
        return 0
    if os.environ.get("INPUT_FAIL_ON", "findings").lower() == "never":
        print("fail-on=never, so the findings above do not fail this step")
        return 0
    return 1


def summary(checks: list[dict], verdict: str, total: int, advisory: int, graph: str,
            repair=None) -> str:
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

    if repair is not None:
        lines += ["", "### Repair suggestions (advisory; not applied)", "",
                  "Finding a candidate does not change the checks or verdict above.", ""]
        text = {"status": repair["status"], "selection": repair.get("selection"),
                "configuration": repair.get("configuration"), "error": repair.get("error"),
                "reason": repair.get("reason"), "trigger_checks": repair.get("trigger_checks")}
        result = repair.get("result", {})
        comparison = result.get("release", {}).get("comparison", {})
        text.update(search=result.get("search"), frontier=result.get("frontier"),
                    reachability={"depth": result.get("search", {}).get("depth"),
                                "released_truncated": comparison.get("before", {}).get("truncated"),
                                "proposed_truncated": comparison.get("after", {}).get("truncated")},
                    discovery={k: v for k, v in result.get("discovery", {}).items()
                               if k != "probes"},
                    candidates=[{"status": c.get("status"), "edits": c.get("edits"),
                                 "impact": c.get("impact"), "lint": c.get("lint"),
                                 "truncated": c.get("authority", {}).get("truncated")}
                                for c in result.get("candidates", []) if isinstance(c, dict)])
        rendered = json.dumps(text, indent=2)
        if len(rendered) > 12000:
            rendered = rendered[:12000] + "\n[Summary shortened; see the repair-report output.]"
        fence = "`" * max(3, 1 + max((len(s) for s in re.findall(r"`+", rendered)), default=0))
        lines += [fence, rendered, fence, "",
                  "Full repair data is in `report` and, when written, `repair-report`."]

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
