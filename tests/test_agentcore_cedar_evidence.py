from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "agentcore-fgac"


def load_capture() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "agentcore_cedar_capture", EVIDENCE / "capture_catalogue.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pinned_agentcore_sources_match_the_offline_index() -> None:
    index = json.loads((EVIDENCE / "source-index.json").read_text(encoding="utf-8"))

    assert index["revision"] == "3e0d462c679c4cddfdea1bfc9176256628c7d699"
    assert len(index["sources"]) == 9
    for source in index["sources"]:
        content = (EVIDENCE / source["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == source["sha256"]


def test_source_catalogue_is_byte_exact_and_refuses_six_tool_completeness() -> None:
    expected = (EVIDENCE / "catalogue.json").read_text(encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "capture_catalogue.py"],
        cwd=EVIDENCE,
        check=True,
        capture_output=True,
        text=True,
    )
    catalogue = json.loads(expected)

    assert result.stdout == expected
    assert result.stderr == ""
    assert catalogue["source_route_count"] == 7
    assert catalogue["mapping_complete"] is False
    assert set(catalogue["source_declared_operation_ids"]) == {
        "add_product",
        "add_to_cart",
        "checkout",
        "list_products",
        "update_price",
        "update_stock",
    }
    health = next(route for route in catalogue["routes"] if route["path"] == "/health")
    assert health == {
        "action": None,
        "backend_access": "public",
        "cedar_admin": "allow",
        "cedar_customer": "deny",
        "line": 19,
        "method": "GET",
        "operation_id": None,
        "path": "/health",
        "source": "upstream/main.py.txt",
    }


def test_capture_object_matches_the_committed_catalogue() -> None:
    module = load_capture()

    assert module.capture() == json.loads(
        (EVIDENCE / "catalogue.json").read_text(encoding="utf-8")
    )


def test_evidence_contains_no_live_identity_or_credential_shapes() -> None:
    forbidden = ("AKIA", "ASIA", "eyJ", "client_secret=")
    for path in EVIDENCE.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            text = path.read_text(encoding="utf-8")
            assert not any(marker in text for marker in forbidden), path
