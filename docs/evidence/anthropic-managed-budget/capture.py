"""Private-first Anthropic Managed Agents budget capture.

The capability and pilot stages are intentionally the only executable stages
until a reviewed pilot cap is committed to protocol.json. Never commit the raw
output produced by this program because it contains live service identifiers.
"""

from __future__ import annotations

import argparse
import json
import os
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
    try:
        from anthropic import Anthropic
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "install the pinned capture requirements before running this program"
        ) from exc
    return Anthropic()


def _all(page: Any) -> list[Any]:
    values: list[Any] = []
    current = page
    while True:
        values.extend(current.data)
        if not current.has_next_page():
            return values
        current = current.get_next_page()


def _wait_idle(client: Any, session_id: str) -> Any:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        session = client.beta.sessions.retrieve(session_id, betas=BETAS)
        if session.status == "idle":
            return session
        if session.status == "terminated":
            raise RuntimeError("managed session terminated before reaching idle")
        time.sleep(POLL_SECONDS)
    raise RuntimeError("managed session did not become idle before the capture timeout")


def _send_work(client: Any, session_id: str, prompt: str) -> Any:
    client.beta.sessions.events.send(
        session_id,
        betas=BETAS,
        events=[
            {
                "type": "user.message",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
    )
    return _wait_idle(client, session_id)


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
            _send_work(client, session.id, protocol["pilot"]["work_unit"])
            _write_json(output / f"pilot-{index + 1}.json", _snapshot(client, session.id))
    finally:
        for session in sessions:
            try:
                client.beta.sessions.delete(session.id, betas=BETAS)
                cleanup.append({"kind": "session", "deleted": True})
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
