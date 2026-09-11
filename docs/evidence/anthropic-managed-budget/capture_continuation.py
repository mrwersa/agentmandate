"""Private-first capture for the preregistered Managed Agents continuation cells.

Never commit the raw output produced by this program because it contains live
service identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = HERE / "continuation-protocol.json"
REFUSAL = "budget.max_list_cost must be greater than the session's consumed list cost"
CONSUME_BOUND = 40
TRIAL_SPEND_ALLOWANCE_CENTS = 12
CELLS = (
    "lowered_cap_carries_spend",
    "cap_at_or_below_spend_refused",
    "agent_update_leaves_live_session",
)


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("budget_capture", HERE / "capture.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the shared budget capture helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


class StopCampaign(RuntimeError):
    """A preregistered stop rule was met."""


def _now() -> dict[str, Any]:
    utc = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    return {"utc": utc.replace("+00:00", "Z"), "monotonic_ns": time.monotonic_ns()}


def _protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _message(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    return str(exc)


def _cap(session: Any) -> int | None:
    if session.budget is None:
        return None
    return int(session.budget.max_list_cost.amount)


def _documentation(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = []
    for url in protocol["documentation_snapshots"]:
        request = urllib.request.Request(url, headers={"User-Agent": "agentmandate-evidence"})
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
        snapshots.append(
            {
                "url": url,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "fetched": _now(),
            }
        )
    return snapshots


def _unit(client: Any, session_id: str, prompt: str, index: int) -> dict[str, Any]:
    started = _now()
    BASE._send_work(client, session_id, prompt)
    snapshot = BASE._snapshot(client, session_id)
    return {
        "work_unit": index,
        "started": started,
        "finished": _now(),
        "list_cost_minor_units": BASE._list_cost(snapshot),
        "idle_reason": BASE._idle_reason(snapshot),
        "session_status": snapshot["session"].status,
        "snapshot": snapshot,
    }


def _consume(
    client: Any, session_id: str, prompt: str, target: int, units: list[dict[str, Any]]
) -> int:
    for _ in range(CONSUME_BOUND):
        unit = _unit(client, session_id, prompt, len(units) + 1)
        units.append(unit)
        if unit["idle_reason"] == "budget_reached":
            raise RuntimeError("session reached its budget before the transition point")
        if unit["list_cost_minor_units"] >= target:
            return unit["list_cost_minor_units"]
    raise RuntimeError("consumption bound reached before the transition point")


def _run_to_budget(
    client: Any, session_id: str, prompt: str, bound: int, units: list[dict[str, Any]]
) -> int:
    for _ in range(bound):
        unit = _unit(client, session_id, prompt, len(units) + 1)
        units.append(unit)
        if unit["idle_reason"] == "budget_reached":
            return unit["list_cost_minor_units"]
    raise RuntimeError("work-unit bound reached without budget_reached")


def _refusal_probe(client: Any, session_id: str, prompt: str) -> dict[str, Any]:
    try:
        client.beta.sessions.events.send(
            session_id,
            betas=BASE.BETAS,
            events=[{"type": "user.message", "content": [{"type": "text", "text": prompt}]}],
        )
    except Exception as exc:  # noqa: BLE001 - native refusal is the observation
        if not BASE._is_anthropic_error(exc):
            raise
        return {
            "error_type": type(exc).__name__,
            "status_code": getattr(exc, "status_code", None),
            "message": _message(exc),
        }
    raise RuntimeError("session accepted new work after reporting budget_reached")


def _lowered_cap(context: dict[str, Any], record: dict[str, Any]) -> None:
    client, cell = context["client"], context["protocol"]["cells"]["lowered_cap_carries_spend"]
    session = BASE._create_budget_session(
        client, context["agent"], context["environment"], cell["create_cap_cents"], record["meta"]
    )
    record["sessions"].append(session.id)
    record["before_update"], record["after_update"] = [], []
    reported = _consume(
        client,
        session.id,
        context["prompt"],
        cell["consume_until_reported_cents_at_least"],
        record["before_update"],
    )
    lowered = reported + 2
    record["update"] = {"requested": _now(), "reported_cents": reported, "requested_cap": lowered}
    response = client.beta.sessions.update(
        session.id, budget=BASE._budget(lowered), betas=BASE.BETAS
    )
    echoed = client.beta.sessions.retrieve(session.id, betas=BASE.BETAS)
    record["update"].update(
        {"completed": _now(), "response_cap": _cap(response), "retrieved_cap": _cap(echoed)}
    )
    if _cap(echoed) != lowered:
        raise RuntimeError("lowered cap was not echoed before more work")
    final = _run_to_budget(
        client, session.id, context["prompt"], context["bound"], record["after_update"]
    )
    added = final - reported
    record["post_budget_refusal"] = _refusal_probe(client, session.id, context["prompt"])
    if added <= 3:
        classification = "carry"
    elif added >= 5:
        classification = "reset"
    else:
        classification = "indeterminate"
    record["result"] = {
        "final_reported_cents": final,
        "added_cents": added,
        "classification": classification,
    }


def _cap_refused(context: dict[str, Any], record: dict[str, Any]) -> None:
    client = context["client"]
    cell = context["protocol"]["cells"]["cap_at_or_below_spend_refused"]
    session = BASE._create_budget_session(
        client, context["agent"], context["environment"], cell["create_cap_cents"], record["meta"]
    )
    record["sessions"].append(session.id)
    record["before_update"] = []
    reported = _consume(
        client,
        session.id,
        context["prompt"],
        cell["consume_until_reported_cents_at_least"],
        record["before_update"],
    )
    attempted = reported - 1
    refusal = None
    started = _now()
    try:
        client.beta.sessions.update(session.id, budget=BASE._budget(attempted), betas=BASE.BETAS)
    except Exception as exc:  # noqa: BLE001 - native refusal is the observation
        if not BASE._is_anthropic_error(exc):
            raise
        refusal = {
            "error_type": type(exc).__name__,
            "status_code": getattr(exc, "status_code", None),
            "message": _message(exc),
        }
    retrieved = _cap(client.beta.sessions.retrieve(session.id, betas=BASE.BETAS))
    refused = (
        refusal is not None
        and refusal["status_code"] == 400
        and REFUSAL in refusal["message"]
        and retrieved == cell["create_cap_cents"]
    )
    record["result"] = {
        "reported_cents": reported,
        "attempted_cap": attempted,
        "requested": started,
        "completed": _now(),
        "refusal": refusal,
        "retrieved_cap": retrieved,
        "classification": "refused" if refused else "not_refused",
    }


def _agent_update(context: dict[str, Any], record: dict[str, Any]) -> None:
    client, protocol = context["client"], context["protocol"]
    cell = protocol["cells"]["agent_update_leaves_live_session"]
    agent = client.beta.agents.create(
        name=f"agentmandate-continuation-agent-{record['trial']}",
        model=protocol["model"],
        system=protocol["agent"]["system"],
        tools=protocol["agent"]["tools"],
        betas=BASE.BETAS,
    )
    record["agents"].append(agent.id)
    session = BASE._create_budget_session(
        client, agent, context["environment"], cell["create_cap_cents"], record["meta"]
    )
    record["sessions"].append(session.id)
    record["before_update"], record["after_update"] = [], []
    reported = _consume(
        client,
        session.id,
        context["prompt"],
        cell["consume_until_reported_cents_at_least"],
        record["before_update"],
    )
    started = _now()
    updated = client.beta.agents.update(
        agent.id,
        version=agent.version,
        description=f"Continuation evidence agent revision {record['trial']}",
        betas=BASE.BETAS,
    )
    during = client.beta.sessions.retrieve(session.id, betas=BASE.BETAS)
    record["agent_update"] = {
        "requested": started,
        "completed": _now(),
        "reported_cents": reported,
        "original_version": agent.version,
        "updated_version": updated.version,
        "session_version_after_update": during.agent.version,
    }
    if updated.version != agent.version + 1:
        raise RuntimeError("agent update did not create exactly one new version")
    final = _run_to_budget(
        client, session.id, context["prompt"], context["bound"], record["after_update"]
    )
    after = client.beta.sessions.retrieve(session.id, betas=BASE.BETAS)
    pinned = during.agent.version == agent.version and after.agent.version == agent.version
    if pinned and final <= 7:
        classification = "pinned_and_retained"
    elif final >= 8:
        classification = "reset"
    else:
        classification = "indeterminate"
    record["result"] = {
        "final_reported_cents": final,
        "session_version_at_budget": after.agent.version,
        "classification": classification,
    }


RUNNERS = {
    "lowered_cap_carries_spend": _lowered_cap,
    "cap_at_or_below_spend_refused": _cap_refused,
    "agent_update_leaves_live_session": _agent_update,
}


def _spent(client: Any, session_ids: list[str]) -> int:
    total = 0
    for session_id in session_ids:
        session = client.beta.sessions.retrieve(session_id, betas=BASE.BETAS)
        total += int(session.usage.list_cost.amount)
    return total


def _pilot(context: dict[str, Any], output: Path) -> dict[str, Any]:
    client, protocol = context["client"], context["protocol"]
    runs = []
    for index in range(protocol["pilot"]["sessions"]):
        session = client.beta.sessions.create(
            agent={"type": "agent", "id": context["agent"].id, "version": context["agent"].version},
            environment_id=context["environment"].id,
            metadata={"study": "continuation-pilot", "trial": str(index + 1)},
            betas=BASE.BETAS,
        )
        context["sessions"].append(session.id)
        units: list[dict[str, Any]] = []
        reported = _consume(client, session.id, context["prompt"], 2, units)
        runs.append(
            {"session": index + 1, "units": units, "units_per_cent": len(units) / reported}
        )
    median = statistics.median(run["units_per_cent"] for run in runs)
    summary = {
        "excluded_from_results": True,
        "median_units_per_reported_cent": median,
        "continue": median >= 2,
    }
    BASE._write_json(output / "pilot.json", {**summary, "runs": runs})
    context["spent"] += _spent(client, context["sessions"])
    return summary


def _confirm(context: dict[str, Any], output: Path) -> None:
    client, protocol = context["client"], context["protocol"]
    order = [
        {"cell": cell, "trial": trial}
        for cell in CELLS
        for trial in range(1, protocol["trials_per_cell"] + 1)
    ]
    random.Random(protocol["random_seed"]).shuffle(order)
    BASE._write_json(output / "cell-order.json", order)
    ceiling = protocol["spend_ceiling_usd"] * 100
    nonconforming = dict.fromkeys(CELLS, 0)
    for position, item in enumerate(order, 1):
        if context["spent"] + TRIAL_SPEND_ALLOWANCE_CENTS > ceiling:
            raise StopCampaign("projected spend exceeds the preregistered ceiling")
        record: dict[str, Any] = {
            "order": position,
            **item,
            "started": _now(),
            "sessions": [],
            "agents": [],
            "meta": {
                "study": "continuation",
                "cell": item["cell"],
                "trial": str(item["trial"]),
                "mandate_sha256": protocol["mandate"]["sha256"],
            },
        }
        try:
            RUNNERS[item["cell"]](context, record)
            record["conforming"] = True
        except Exception as exc:  # noqa: BLE001 - nonconforming trials are retained
            if not (BASE._is_anthropic_error(exc) or isinstance(exc, RuntimeError)):
                raise
            record["conforming"] = False
            record["error"] = {"type": type(exc).__name__, "message": _message(exc)}
            nonconforming[item["cell"]] += 1
        finally:
            record["finished"] = _now()
            context["sessions"].extend(record["sessions"])
            context["agents"].extend(record["agents"])
            context["spent"] += _spent(client, record["sessions"])
            BASE._write_json(output / f"trial-{position:02d}.json", record)
        if nonconforming[item["cell"]] > 2:
            raise StopCampaign(f"more than two nonconforming trials in {item['cell']}")


def _cleanup(context: dict[str, Any]) -> list[dict[str, Any]]:
    client, cleanup = context["client"], []
    for session_id in context["sessions"]:
        try:
            BASE._delete_session(client, session_id)
            cleanup.append({"kind": "session", "deleted": True, "verified_absent": True})
        except Exception as exc:  # noqa: BLE001 - cleanup failures are retained
            cleanup.append({"kind": "session", "deleted": False, "error": type(exc).__name__})
    for agent_id in context["agents"]:
        try:
            client.beta.agents.archive(agent_id, betas=BASE.BETAS)
            cleanup.append({"kind": "agent", "archived": True})
        except Exception as exc:  # noqa: BLE001 - cleanup failures are retained
            cleanup.append({"kind": "agent", "archived": False, "error": type(exc).__name__})
    if context["environment"] is not None:
        try:
            client.beta.environments.delete(context["environment"].id, betas=BASE.BETAS)
            cleanup.append({"kind": "environment", "deleted": True})
        except Exception as exc:  # noqa: BLE001 - cleanup failures are retained
            cleanup.append(
                {"kind": "environment", "deleted": False, "error": type(exc).__name__}
            )
    return cleanup


def run(output: Path) -> int:
    protocol = _protocol()
    output.mkdir(parents=True, exist_ok=False)
    client = BASE._client()
    context: dict[str, Any] = {
        "client": client,
        "protocol": protocol,
        "prompt": protocol["work_unit"],
        "bound": protocol["work_unit_bound_after_transition"],
        "environment": None,
        "agent": None,
        "sessions": [],
        "agents": [],
        "spent": 0,
    }
    outcome = {"started": _now(), "stopped": None}
    try:
        BASE._write_json(output / "documentation.json", _documentation(protocol))
        context["environment"] = client.beta.environments.create(
            name="agentmandate-continuation",
            config=protocol["environment"],
            betas=BASE.BETAS,
        )
        context["agent"] = client.beta.agents.create(
            name="agentmandate-continuation",
            model=protocol["model"],
            system=protocol["agent"]["system"],
            tools=protocol["agent"]["tools"],
            betas=BASE.BETAS,
        )
        context["agents"].append(context["agent"].id)
        outcome["model"] = context["agent"].model.id
        pilot = _pilot(context, output)
        if not pilot["continue"]:
            raise StopCampaign("pilot continue_rule failed")
        _confirm(context, output)
    except StopCampaign as exc:
        outcome["stopped"] = str(exc)
    finally:
        cleanup = _cleanup(context)
        BASE._write_json(output / "cleanup.json", cleanup)
        outcome.update(
            {
                "finished": _now(),
                "spent_reported_cents": context["spent"],
                "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
                "cleanup_complete": all(
                    item.get("deleted") or item.get("archived") for item in cleanup
                ),
            }
        )
        BASE._write_json(output / "run.json", outcome)
    return 3 if outcome["stopped"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        return run(args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
