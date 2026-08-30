"""Private-first Anthropic Managed Agents budget capture.

The capability and pilot stages are intentionally the only executable stages
until a reviewed pilot cap is committed to protocol.json. Never commit the raw
output produced by this program because it contains live service identifiers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = HERE / "protocol.json"
BETAS = ["managed-agents-2026-04-01"]
POLL_SECONDS = 0.5
TIMEOUT_SECONDS = 180
WORKSPACE_ID = re.compile(r"^wrkspc_[A-Za-z0-9]+$")


def _load_protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(_jsonable(value), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _client() -> Any:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID", "")
    if not WORKSPACE_ID.fullmatch(workspace_id):
        raise RuntimeError("ANTHROPIC_WORKSPACE_ID is not set to a valid workspace ID")
    try:
        from anthropic import Anthropic
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "install the pinned capture requirements before running this program"
        ) from exc
    return Anthropic(default_headers={"anthropic-workspace-id": workspace_id})


def _all(page: Any) -> list[Any]:
    values: list[Any] = []
    current = page
    while True:
        values.extend(current.data)
        if not current.has_next_page():
            return values
        current = current.get_next_page()


def _wait_idle(client: Any, session_id: str, event_id: str) -> Any:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        session = client.beta.sessions.retrieve(session_id, betas=BETAS)
        events = _all(
            client.beta.sessions.events.list(
                session_id,
                order="asc",
                limit=100,
                betas=BETAS,
            )
        )
        sent_positions = [index for index, event in enumerate(events) if event.id == event_id]
        completed = bool(sent_positions) and any(
            index > sent_positions[0] and event.type == "session.status_idle"
            for index, event in enumerate(events)
        )
        if completed and session.status == "idle":
            return session
        if session.status == "terminated":
            raise RuntimeError("managed session terminated before reaching idle")
        time.sleep(POLL_SECONDS)
    raise RuntimeError("managed session did not become idle before the capture timeout")


def _send_work(client: Any, session_id: str, prompt: str) -> Any:
    sent = client.beta.sessions.events.send(
        session_id,
        betas=BETAS,
        events=[
            {
                "type": "user.message",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
    )
    if sent.data is None or len(sent.data) != 1:
        raise RuntimeError("managed API did not acknowledge exactly one work event")
    return _wait_idle(client, session_id, sent.data[0].id)


def _delete_session(client: Any, session_id: str) -> None:
    try:
        client.beta.sessions.delete(session_id, betas=BETAS)
    except Exception:  # noqa: BLE001 - inspect state before retrying managed cleanup
        current = client.beta.sessions.retrieve(session_id, betas=BETAS)
        if current.status != "running":
            raise
        sent = client.beta.sessions.events.send(
            session_id,
            betas=BETAS,
            events=[{"type": "user.interrupt"}],
        )
        if sent.data is None or len(sent.data) != 1:
            raise RuntimeError("managed API did not acknowledge cleanup interrupt") from None
        _wait_idle(client, session_id, sent.data[0].id)
        client.beta.sessions.delete(session_id, betas=BETAS)
    try:
        client.beta.sessions.retrieve(session_id, betas=BETAS)
    except Exception as exc:  # noqa: BLE001 - a typed not-found is the absence proof
        if _is_anthropic_error(exc) and type(exc).__name__ == "NotFoundError":
            return
        raise
    raise RuntimeError("managed session still resolves after deletion")


def _snapshot(client: Any, session_id: str) -> dict[str, Any]:
    session = client.beta.sessions.retrieve(session_id, betas=BETAS)
    events = _all(
        client.beta.sessions.events.list(
            session_id,
            order="asc",
            limit=100,
            betas=BETAS,
        )
    )
    threads = _all(client.beta.sessions.threads.list(session_id, limit=100, betas=BETAS))
    return {"session": session, "events": events, "threads": threads}


def _list_cost(snapshot: dict[str, Any]) -> int:
    value = snapshot["session"].usage.list_cost.amount
    if not isinstance(value, str) or not value.isdigit():
        raise RuntimeError("managed session returned a non-canonical list cost")
    return int(value)


def capability(output: Path) -> None:
    client = _client()
    output.mkdir(parents=True, exist_ok=False)
    agents = _all(client.beta.agents.list(limit=1, betas=BETAS))
    environments = _all(client.beta.environments.list(limit=1, betas=BETAS))
    _write_json(
        output / "capability.json",
        {
            "managed_agents_api_reachable": True,
            "listed_agent_count_at_most_one": len(agents),
            "listed_environment_count_at_most_one": len(environments),
            "beta": BETAS[0],
        },
    )


def pilot(output: Path) -> None:
    protocol = _load_protocol()
    if protocol["confirmation"]["cap_minor_units"] is not None:
        raise RuntimeError("pilot is closed after a confirmation cap is committed")
    client = _client()
    output.mkdir(parents=True, exist_ok=False)
    environment = None
    agent = None
    sessions: list[Any] = []
    cleanup: list[dict[str, Any]] = []
    try:
        environment = client.beta.environments.create(
            name="agentmandate-budget-pilot",
            config={
                "type": "cloud",
                "networking": {
                    "type": "limited",
                    "allowed_hosts": [],
                    "allow_mcp_servers": False,
                    "allow_package_managers": False,
                },
            },
            betas=BETAS,
        )
        agent = client.beta.agents.create(
            name="agentmandate-budget-pilot",
            model=protocol["model"],
            system="Follow the user's output instruction exactly. Do not use tools.",
            tools=[],
            betas=BETAS,
        )
        for index in range(protocol["pilot"]["sessions"]):
            session = client.beta.sessions.create(
                agent={"type": "agent", "id": agent.id, "version": agent.version},
                environment_id=environment.id,
                metadata={"study": "budget-pilot", "trial": str(index + 1)},
                betas=BETAS,
            )
            sessions.append(session)
            snapshots = []
            for work_index in range(protocol["pilot"]["max_work_units_per_session"]):
                _send_work(client, session.id, protocol["pilot"]["work_unit"])
                snapshot = _snapshot(client, session.id)
                snapshots.append(
                    {
                        "work_unit": work_index + 1,
                        "list_cost_minor_units": _list_cost(snapshot),
                        "snapshot": snapshot,
                    }
                )
                if snapshots[-1]["list_cost_minor_units"] > 0:
                    break
            _write_json(
                output / f"pilot-{index + 1}.json",
                {
                    "excluded_from_confirmation": True,
                    "stopping_rule": protocol["pilot"]["stopping_rule"],
                    "work_units": snapshots,
                },
            )
    finally:
        for session in sessions:
            try:
                _delete_session(client, session.id)
                cleanup.append({"kind": "session", "deleted": True, "verified_absent": True})
            except Exception as exc:  # capture must retain cleanup failures
                cleanup.append(
                    {"kind": "session", "deleted": False, "error_type": type(exc).__name__}
                )
        if agent is not None:
            try:
                client.beta.agents.archive(agent.id, betas=BETAS)
                cleanup.append({"kind": "agent", "archived": True})
            except Exception as exc:
                cleanup.append(
                    {"kind": "agent", "archived": False, "error_type": type(exc).__name__}
                )
        if environment is not None:
            try:
                client.beta.environments.delete(environment.id, betas=BETAS)
                cleanup.append({"kind": "environment", "deleted": True})
            except Exception as exc:
                cleanup.append(
                    {"kind": "environment", "deleted": False, "error_type": type(exc).__name__}
                )
        if output.exists():
            _write_json(output / "cleanup.json", cleanup)


def confirm(_: Path) -> None:
    protocol = _load_protocol()
    if protocol["confirmation"]["cap_minor_units"] is None:
        raise RuntimeError(
            "confirmation is locked until the excluded pilot cap is reviewed and committed"
        )
    raise RuntimeError("confirmation implementation is not part of the frozen pilot harness")


def _is_anthropic_error(exc: Exception) -> bool:
    module = type(exc).__module__
    return module == "anthropic" or module.startswith("anthropic.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("capability", "pilot", "confirm"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        {"capability": capability, "pilot": pilot, "confirm": confirm}[args.stage](args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - sanitise SDK errors at the capture boundary
        if not _is_anthropic_error(exc):
            raise
        print(f"error: Anthropic request failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
