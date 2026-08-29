"""Capture the bounded access-key producer in AWS IAM MCP Server 1.0.11.

The published MCP tool returns live credentials. This adapter keeps them in
process memory only, uses each once for STS identity proof, and commits only
aliases and outcome classes. Cleanup runs before either output file is written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import boto3
from awslabs.iam_mcp_server.server import create_access_key, mcp
from loguru import logger

PACKAGE = "awslabs.iam-mcp-server"
PACKAGE_VERSION = "1.0.11"
MCP_VERSION = "1.23.3"
WHEEL_SHA256 = "e48d688f8e338098f410fcabfbedec304f65e63c179bb19001e5b80a2523de16"
REGION = "us-east-1"
USER_PATH = "/agentmandate-evidence/"

logger.disable("awslabs.iam_mcp_server")


def _json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _aws_error_code(exc: BaseException) -> str | None:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        if isinstance(response, dict):
            error = response.get("Error")
            if isinstance(error, dict) and isinstance(error.get("Code"), str):
                return error["Code"]
        current = current.__cause__ or current.__context__
    return None


async def _catalogue() -> dict[str, object]:
    tools = await mcp.list_tools()
    return {
        "tools": [
            tool.model_dump(by_alias=True, exclude_none=True, mode="json")
            for tool in tools
        ]
    }


def _identity(access_key: dict[str, Any], user_name: str) -> dict[str, str]:
    client = boto3.client(
        "sts",
        aws_access_key_id=access_key["AccessKeyId"],
        aws_secret_access_key=access_key["SecretAccessKey"],
        aws_session_token=None,
        region_name=REGION,
    )
    last_error: Exception | None = None
    for _ in range(30):
        try:
            identity = client.get_caller_identity()
            arn = identity["Arn"]
            if not arn.endswith(f"/{user_name}"):
                raise RuntimeError("captured credential authenticated as an unexpected principal")
            return {"arn": arn, "user_id": identity["UserId"]}
        except Exception as exc:  # eventual consistency is an observed service boundary
            last_error = exc
            time.sleep(1)
    raise RuntimeError(
        "captured credential did not authenticate within thirty seconds"
    ) from last_error


async def _live_capture() -> dict[str, object]:
    if version(PACKAGE) != PACKAGE_VERSION or version("mcp") != MCP_VERSION:
        raise RuntimeError("capture dependencies do not match the reviewed versions")

    iam = boto3.client("iam", region_name=REGION)
    user_name = f"agentmandate-bounded-{secrets.token_hex(6)}"
    outcomes: list[dict[str, object]] = []
    identities: list[dict[str, str]] = []
    user_created = False
    cleanup = {"access_keys": -1, "user_absent": False}

    try:
        iam.create_user(UserName=user_name, Path=USER_PATH)
        user_created = True

        for attempt in (1, 2):
            response = await create_access_key(user_name)
            access_key = response["AccessKey"]
            if access_key["Status"] != "Active" or not access_key["SecretAccessKey"]:
                raise RuntimeError("MCP producer did not return an active credential")
            identities.append(_identity(access_key, user_name))
            outcomes.append(
                {
                    "attempt": attempt,
                    "binding": f"access-key-{attempt}",
                    "authenticated": True,
                    "outcome": "created",
                    "status": "Active",
                }
            )

        try:
            await create_access_key(user_name)
        except Exception as exc:
            if _aws_error_code(exc) != "LimitExceeded":
                raise RuntimeError(
                    "third production failed for a reason other than exhaustion"
                ) from exc
            outcomes.append(
                {
                    "attempt": 3,
                    "error_code": "LimitExceeded",
                    "outcome": "rejected",
                }
            )
        else:
            raise RuntimeError("third access-key production unexpectedly succeeded")

        metadata = iam.list_access_keys(UserName=user_name)["AccessKeyMetadata"]
        if len(metadata) != 2 or any(item["Status"] != "Active" for item in metadata):
            raise RuntimeError("live access-key inventory does not match the two-key control")
        if len({item["AccessKeyId"] for item in metadata}) != 2:
            raise RuntimeError("live access-key inventory contains duplicate identifiers")
        if identities[0] != identities[1]:
            raise RuntimeError("the two credentials did not authenticate as the same IAM user")
    finally:
        if user_created:
            for item in iam.list_access_keys(UserName=user_name).get("AccessKeyMetadata", []):
                iam.delete_access_key(UserName=user_name, AccessKeyId=item["AccessKeyId"])
            iam.delete_user(UserName=user_name)
            cleanup["access_keys"] = 0
            try:
                iam.get_user(UserName=user_name)
            except Exception as exc:
                if _aws_error_code(exc) != "NoSuchEntity":
                    raise
                cleanup["user_absent"] = True
            else:
                raise RuntimeError("temporary IAM user still exists after cleanup")

    if len(outcomes) != 3 or cleanup != {"access_keys": 0, "user_absent": True}:
        raise RuntimeError("capture did not complete its success, exhaustion, and cleanup controls")

    return {
        "adapter": {"name": "agentmandate.aws-iam-access-key-capture", "version": 1},
        "capture_date": "2026-08-29",
        "capture_version": 1,
        "cleanup": cleanup,
        "deployment": {
            "attached_policies": [],
            "region": REGION,
            "user_path": USER_PATH,
        },
        "identity": {"principal_kind": "iam-user", "same_principal": True},
        "outcomes": outcomes,
        "producer": {
            "mcp_version": MCP_VERSION,
            "package": PACKAGE,
            "package_version": PACKAGE_VERSION,
            "wheel_sha256": WHEEL_SHA256,
        },
        "quota": {
            "adjustable": False,
            "kind": "access_keys_per_user",
            "maximum": 2,
        },
        "sanitization": {
            "committed_live_identifiers": False,
            "committed_secret_material": False,
            "raw_credentials_written_to_disk": False,
        },
    }


async def _run(catalogue_path: Path, outcome_path: Path, live: bool) -> None:
    catalogue = await _catalogue()
    if not live:
        catalogue_path.write_text(_json(catalogue), encoding="utf-8")
        return

    outcome = await _live_capture()
    # Live output is written only after the finally cleanup and its absence check.
    catalogue_path.write_text(_json(catalogue), encoding="utf-8")
    outcome_path.write_text(_json(outcome), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--outcome", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(args.catalogue, args.outcome, args.live))


if __name__ == "__main__":
    main()
