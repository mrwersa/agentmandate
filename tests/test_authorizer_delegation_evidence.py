import hashlib
import json
import re
from pathlib import Path

EVIDENCE = (
    Path(__file__).resolve().parents[1] / "docs" / "evidence" / "authorizer-delegation"
)
CAPTURE_SHA256 = "bbbe73c3b138fa9e6e207e3958971bc92f2f91b771967fb5252c1c0d7b8f0409"


def load_capture() -> dict:
    return json.loads((EVIDENCE / "capture.json").read_text(encoding="utf-8"))


def test_capture_is_canonical_and_digest_pinned() -> None:
    content = (EVIDENCE / "capture.json").read_bytes()
    capture = json.loads(content)

    assert hashlib.sha256(content).hexdigest() == CAPTURE_SHA256
    assert content.decode() == json.dumps(capture, sort_keys=True, indent=2) + "\n"


def test_capture_preserves_subject_actor_order_and_attenuation() -> None:
    capture = load_capture()
    hops = capture["hops"]

    assert [hop["hop"] for hop in hops] == [1, 2, 3, 4]
    assert {hop["subject"] for hop in hops} == {"subject:demo-user"}
    assert [hop["actor"] for hop in hops] == [
        "agent:orchestrator",
        "agent:research-agent",
        "agent:crm-reader",
        "agent:export-agent",
    ]
    for index, hop in enumerate(hops):
        assert hop["actor_chain"][0] == hop["actor"]
        assert len(hop["actor_chain"]) == index + 1
        assert hop["ttl_seconds"] == 300
        assert hop["grantor"] == "http://localhost:8080"
        assert "tools" not in hop
        assert "effects" not in hop
        assert set(hop["scopes"]).issubset(hops[0]["scopes"])
        if index:
            assert set(hop["scopes"]).issubset(hops[index - 1]["scopes"])

    assert hops[-1]["actor_chain"] == [
        "agent:export-agent",
        "agent:crm-reader",
        "agent:research-agent",
        "agent:orchestrator",
    ]


def test_capture_preserves_all_fail_closed_results() -> None:
    assert {
        item["name"]: (item["http_status"], item["error"])
        for item in load_capture()["rejections"]
    } == {
        "chain_depth": (400, "invalid_request"),
        "scope_rewidening": (400, "invalid_scope"),
        "actor_substitution": (400, "invalid_grant"),
    }


def test_capture_contains_no_raw_identity_or_token_material() -> None:
    content = (EVIDENCE / "capture.json").read_text(encoding="utf-8")

    assert '"access_token":' not in content
    assert '"client_secret":' not in content
    assert "session" not in content
    assert not re.search(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.", content)
    assert not re.search(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        content,
    )
    assert not re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", content)


def test_capture_adapter_is_loopback_only_and_dependency_free() -> None:
    source = (EVIDENCE / "capture-delegation.mjs").read_text(encoding="utf-8")

    assert '["localhost", "127.0.0.1"].includes(target.hostname)' in source
    assert 'target.port !== "8080"' in source
    assert 'from "node:fs"' in source
    assert "node_modules" not in source
    assert "SETTLE_MS = 2100" in source
