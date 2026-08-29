"""Verify an issuer-signed mandate binding and derive one policy-session identifier."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIELDS = {
    "binding_version",
    "mandate_sha256",
    "principal",
    "policy_sha256",
    "issued_at",
    "expires_at",
    "issuer",
    "signature",
}
SIGNED_FIELDS = FIELDS - {"signature"}
SHA256 = re.compile(r"[0-9a-f]{64}")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class BindingError(ValueError):
    """The mandate binding is malformed, untrusted, or ineligible."""


def _timestamp(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or TIMESTAMP.fullmatch(value) is None:
        raise BindingError(f"{path} must be a canonical UTC timestamp")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _body(binding: dict[str, Any]) -> dict[str, Any]:
    if set(binding) != FIELDS:
        raise BindingError("binding has missing or unknown fields")
    if type(binding["binding_version"]) is not int or binding["binding_version"] != 1:
        raise BindingError("binding_version must be 1")
    for field in ("mandate_sha256", "policy_sha256"):
        if not isinstance(binding[field], str) or SHA256.fullmatch(binding[field]) is None:
            raise BindingError(f"{field} must be a lowercase SHA-256 digest")
    for field in ("principal", "issuer"):
        value = binding[field]
        if not isinstance(value, str) or not value or value.strip() != value:
            raise BindingError(f"{field} must be a non-empty stripped string")
    issued_at = _timestamp(binding["issued_at"], "issued_at")
    expires_at = _timestamp(binding["expires_at"], "expires_at")
    if issued_at >= expires_at:
        raise BindingError("binding validity window must be increasing")
    if not isinstance(binding["signature"], str) or not binding["signature"]:
        raise BindingError("signature must be non-empty base64")
    return {field: binding[field] for field in sorted(SIGNED_FIELDS)}


def canonical_body(binding: dict[str, Any]) -> bytes:
    """Return the exact bytes covered by the issuer signature."""
    return json.dumps(_body(binding), sort_keys=True, separators=(",", ":")).encode()


def verify_and_derive(
    binding: dict[str, Any],
    public_key_pem: bytes,
    *,
    as_of: datetime,
    expected_principal: str,
) -> str:
    """Verify one binding and derive its stable provider-compatible session ID."""
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise BindingError("as_of must be a timezone-aware datetime")
    body = canonical_body(binding)
    issued_at = _timestamp(binding["issued_at"], "issued_at")
    expires_at = _timestamp(binding["expires_at"], "expires_at")
    if not issued_at <= as_of.astimezone(timezone.utc) < expires_at:
        raise BindingError("binding is not active at as_of")
    if binding["principal"] != expected_principal:
        raise BindingError("binding principal does not match the authenticated caller")
    try:
        signature = base64.b64decode(binding["signature"], validate=True)
    except (binascii.Error, ValueError) as error:
        raise BindingError("signature must be non-empty base64") from error
    with tempfile.TemporaryDirectory(prefix="mandate-binding-") as directory:
        root = Path(directory)
        key_path = root / "issuer-public.pem"
        body_path = root / "binding-body.json"
        signature_path = root / "binding.sig"
        key_path.write_bytes(public_key_pem)
        body_path.write_bytes(body)
        signature_path.write_bytes(signature)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(key_path),
                "-rawin",
                "-in",
                str(body_path),
                "-sigfile",
                str(signature_path),
            ],
            check=False,
            capture_output=True,
        )
    if result.returncode != 0:
        raise BindingError("binding signature is not valid for the reviewed issuer")
    digest = hashlib.sha256(body).digest()
    return str(uuid.UUID(bytes=digest[:16], version=5))
