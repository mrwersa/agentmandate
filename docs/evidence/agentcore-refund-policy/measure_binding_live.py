"""Measure the reviewed mandate-binding adapter through one managed Gateway call."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import platform
import secrets
import statistics
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import botocore
import botocore.auth
import botocore.awsrequest
import botocore.session

ADAPTER_ONLY_MEDIAN_MS = 13.602295


def load_binding_module(path: Path) -> ModuleType:
    """Load the separately reviewed reference adapter."""
    spec = importlib.util.spec_from_file_location("mandate_binding_live", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("binding module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sign_binding(
    module: ModuleType,
    private_key: Path,
    root: Path,
    run_nonce: str,
    index: int,
) -> dict[str, Any]:
    """Create one independently signed, ephemeral mandate binding."""
    binding = {
        "binding_version": 1,
        "mandate_sha256": hashlib.sha256(
            f"independent-mandate-{run_nonce}-{index}".encode()
        ).hexdigest(),
        "principal": "caller",
        "policy_sha256": hashlib.sha256(b"reviewed temporal sum policy v1").hexdigest(),
        "issued_at": "2026-08-30T00:00:00Z",
        "expires_at": "2026-08-31T00:00:00Z",
        "issuer": "review-control-plane-live-latency",
        "signature": "AA==",
    }
    body = module.canonical_body(binding)
    body_path = root / f"binding-{index}.json"
    signature_path = root / f"binding-{index}.sig"
    body_path.write_bytes(body)
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private_key),
            "-rawin",
            "-in",
            str(body_path),
            "-out",
            str(signature_path),
        ],
        check=True,
        capture_output=True,
    )
    binding["signature"] = base64.b64encode(signature_path.read_bytes()).decode()
    return binding


def _signed_request(url: str, body: bytes, session_id: str) -> urllib.request.Request:
    credentials = botocore.session.get_session().get_credentials()
    if credentials is None:
        raise RuntimeError("AWS credentials are unavailable")
    request = botocore.awsrequest.AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={
            "content-type": "application/json",
            "x-amzn-bedrock-agentcore-policy-session-id": session_id,
        },
    )
    botocore.auth.SigV4Auth(
        credentials.get_frozen_credentials(), "bedrock-agentcore", "us-east-1"
    ).add_auth(request)
    prepared = request.prepare()
    return urllib.request.Request(
        prepared.url,
        data=prepared.body,
        headers=dict(prepared.headers),
        method="POST",
    )


def managed_call(url: str, tool: str, session_id: str, identifier: str) -> dict[str, Any]:
    """Call the inert managed tool once and return the native response."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": identifier,
            "method": "tools/call",
            "params": {"name": tool, "arguments": {"amount": 600}},
        },
        separators=(",", ":"),
    ).encode()
    wire = _signed_request(url, body, session_id)
    try:
        with urllib.request.urlopen(wire, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        payload = error.read()
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise RuntimeError("managed call did not return a JSON object")
    return value


def managed_inventory(url: str) -> list[str]:
    """Return the exact native tools/list name set for the measured Gateway."""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": "inventory", "method": "tools/list", "params": {}},
        separators=(",", ":"),
    ).encode()
    wire = _signed_request(url, body, str(uuid.uuid4()))
    with urllib.request.urlopen(wire, timeout=60) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise RuntimeError("managed tools/list did not return a JSON object")
    result = payload.get("result")
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list) or any(not isinstance(item, dict) for item in tools):
        raise RuntimeError("managed tools/list did not return a tool array")
    names = [item.get("name") for item in tools]
    if any(not isinstance(name, str) for name in names):
        raise RuntimeError("managed tools/list contained an invalid name")
    return sorted(names)


def measure(args: argparse.Namespace) -> dict[str, Any]:
    """Run the live experiment and return its sanitised result."""
    if args.warmups < 0 or args.samples < 1:
        raise ValueError("warmups must be non-negative and samples must be positive")
    module = load_binding_module(args.binding_module)
    inventory = managed_inventory(args.url)
    if inventory != [args.tool]:
        raise RuntimeError("managed tool inventory did not equal the measured singleton")
    durations: list[float] = []
    outcomes: list[str] = []
    run_nonce = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="mandate-binding-live-") as directory:
        root = Path(directory)
        private_key = root / "private.pem"
        public_key = root / "public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(private_key)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
            check=True,
            capture_output=True,
        )
        args.public_key_output.write_bytes(public_key.read_bytes())
        public_key_bytes = public_key.read_bytes()
        for index in range(args.warmups + args.samples):
            binding = sign_binding(module, private_key, root, run_nonce, index)
            started = time.perf_counter_ns()
            session_id = module.verify_and_derive(
                binding,
                public_key_bytes,
                as_of=datetime(2026, 8, 30, 0, 30, tzinfo=timezone.utc),
                expected_principal="caller",
            )
            response = managed_call(args.url, args.tool, session_id, f"latency-{index}")
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            result = response.get("result")
            allowed = (
                response.get("error") is None
                and isinstance(result, dict)
                and result.get("isError") is False
            )
            if not allowed:
                raise RuntimeError(f"measured managed call {index} was not allowed")
            if index >= args.warmups:
                durations.append(elapsed_ms)
                outcomes.append("allow")
    median_ms = statistics.median(durations)
    return {
        "binding_live_latency_version": 1,
        "adapter_only_median_ms": ADAPTER_ONLY_MEDIAN_MS,
        "end_to_end_median_ms": round(median_ms, 6),
        "end_to_end_minimum_ms": round(min(durations), 6),
        "end_to_end_maximum_ms": round(max(durations), 6),
        "ratio_of_adapter_only_median_to_end_to_end_median_percent": round(
            ADAPTER_ONLY_MEDIAN_MS / median_ms * 100, 6
        ),
        "warmups": args.warmups,
        "samples": args.samples,
        "amount": 600,
        "outcomes": outcomes,
        "independent_signed_mandates": args.samples,
        "end_to_end_samples_ms": [round(value, 6) for value in durations],
        "tool_inventory": inventory,
        "tool_inventory_complete": True,
        "request_domain": "representative",
        "policy_session_identity": "derived from each signed mandate",
        "timing_boundary": (
            "binding verification and session derivation through complete managed Gateway response"
        ),
        "environment": {
            "botocore": botocore.__version__,
            "implementation": platform.python_implementation(),
            "openssl": subprocess.run(
                ["openssl", "version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "region": "us-east-1",
            "protocol": "MCP 2025-03-26",
        },
        "committed_live_identifiers": False,
        "committed_credentials": False,
        "gateway_verified_binding": False,
        "credential_path": "exclusive trusted adapter",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--binding-module", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--public-key-output", required=True, type=Path)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    result = measure(args)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
