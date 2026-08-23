import json
from pathlib import Path

import pytest

from agentmandate._inventory import DynamicInventory, InventoryFormatError

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
AGENTKIT = FIXTURES / "dynamic-inventory-agentkit-v1.json"
SENTRY = FIXTURES / "dynamic-inventory-sentry-v1.json"


def raw_fixture(path: Path = AGENTKIT) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def encoded(raw: object) -> str:
    return json.dumps(raw, separators=(",", ":"))


@pytest.mark.parametrize(
    ("fixture", "source", "complete", "members"),
    [
        (
            AGENTKIT,
            ROOT / "docs" / "evidence" / "agentkit" / "inventory-v074.json",
            "complete",
            20,
        ),
        (
            SENTRY,
            ROOT / "docs" / "evidence" / "sentry-mcp" / "catalogue.json",
            "partial",
            8,
        ),
    ],
)
def test_canonical_evidence_fixtures_round_trip_and_verify_source(
    fixture: Path, source: Path, complete: str, members: int
) -> None:
    text = fixture.read_text(encoding="utf-8")
    declaration = DynamicInventory.from_json(text)

    assert declaration.to_json() == text
    assert declaration.membership.completeness == complete
    assert len(declaration.membership.members) == members
    declaration.verify_source(source.read_bytes())


def test_agentkit_members_are_the_distinct_preserved_provider_actions() -> None:
    source = json.loads(
        (ROOT / "docs" / "evidence" / "agentkit" / "inventory-v074.json").read_text(
            encoding="utf-8"
        )
    )
    actions = [tool for provider in source["providers"] for tool in provider["tools"]]
    declaration = DynamicInventory.from_json(AGENTKIT.read_text(encoding="utf-8"))

    assert len(actions) == 21
    assert len(set(actions)) == 20
    assert set(declaration.membership.members) == set(actions)


def test_sentry_partial_members_are_exactly_the_visible_catalogue() -> None:
    source = json.loads(
        (ROOT / "docs" / "evidence" / "sentry-mcp" / "catalogue.json").read_text(
            encoding="utf-8"
        )
    )
    declaration = DynamicInventory.from_json(SENTRY.read_text(encoding="utf-8"))

    assert set(declaration.membership.members) == {
        tool["name"] for tool in source["tools"]
    }
    assert declaration.membership.completeness == "partial"


def test_canonicalization_sorts_members_selection_keys_and_list_values() -> None:
    raw = raw_fixture()
    raw["membership"]["members"].reverse()
    raw["selection"] = {
        "skills": ["triage", "inspect"],
        "environment": "production",
    }

    declaration = DynamicInventory.from_json(encoded(raw))
    rendered = declaration.as_dict()

    assert list(rendered["selection"]) == ["environment", "skills"]
    assert rendered["selection"]["skills"] == ["inspect", "triage"]
    assert rendered["membership"]["members"] == sorted(
        rendered["membership"]["members"]
    )


def test_an_empty_selection_is_valid() -> None:
    raw = raw_fixture()
    raw["selection"] = {}

    assert DynamicInventory.from_json(encoded(raw)).selection == ()


def test_source_verification_rejects_tampering_and_non_bytes() -> None:
    declaration = DynamicInventory.from_json(AGENTKIT.read_text(encoding="utf-8"))

    with pytest.raises(InventoryFormatError, match="does not match supplied bytes"):
        declaration.verify_source(b"tampered")
    with pytest.raises(InventoryFormatError, match="content must be bytes"):
        declaration.verify_source("not bytes")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(inventory_version=True), "version type"),
        (lambda raw: raw.update(inventory_version=2), "version 2"),
        (lambda raw: raw["boundary"].update(id=""), "id must be a non-empty string"),
        (lambda raw: raw["boundary"].update(id=" padded "), "non-empty string"),
        (lambda raw: raw["boundary"].update(kind="other"), "kind has an invalid value"),
        (
            lambda raw: raw["boundary"]["target"].update(source="/absolute.py"),
            "safe relative POSIX path",
        ),
        (
            lambda raw: raw["boundary"]["target"].update(source="../agent.py"),
            "safe relative POSIX path",
        ),
        (
            lambda raw: raw["boundary"]["target"].update(source="src\\agent.py"),
            "safe relative POSIX path",
        ),
        (
            lambda raw: raw["boundary"]["target"].update(source="src/./agent.py"),
            "safe relative POSIX path",
        ),
        (
            lambda raw: raw["boundary"]["target"].update(source="."),
            "safe relative POSIX path",
        ),
        (lambda raw: raw.update(selection=[]), "selection must be an object"),
        (lambda raw: raw.update(selection={"token": "unsafe"}), "unsupported key"),
        (lambda raw: raw.update(selection={"skills": ""}), "non-empty string"),
        (lambda raw: raw.update(selection={"skills": []}), "non-empty string"),
        (
            lambda raw: raw.update(selection={"skills": ["inspect", "inspect"]}),
            "must not contain duplicates",
        ),
        (
            lambda raw: raw["source"].update(content_sha256="A" * 64),
            "lowercase SHA-256",
        ),
        (
            lambda raw: raw["source"].update(locator="../capture.json"),
            "safe relative POSIX path",
        ),
        (
            lambda raw: raw["membership"].update(relation="contains_agent"),
            "relation has an invalid value",
        ),
        (
            lambda raw: raw["membership"].update(completeness="mostly"),
            "completeness has an invalid value",
        ),
        (
            lambda raw: raw["membership"].update(members="tool"),
            "array of non-empty strings",
        ),
        (
            lambda raw: raw["membership"].update(members=[""]),
            "array of non-empty strings",
        ),
        (
            lambda raw: raw["membership"].update(members=["tool", "tool"]),
            "must not contain duplicates",
        ),
        (
            lambda raw: raw["evidence"].update(confidence="certain"),
            "confidence has an invalid value",
        ),
        (
            lambda raw: raw["evidence"].update(review="pending"),
            "review has an invalid value",
        ),
        (
            lambda raw: raw["evidence"].update(reviewer=7),
            "reviewer must be a non-empty string or null",
        ),
        (
            lambda raw: raw["evidence"].update(review="unreviewed"),
            "unreviewed evidence cannot name",
        ),
        (
            lambda raw: raw["evidence"].update(reviewer=None),
            "reviewed evidence requires",
        ),
        (
            lambda raw: raw["evidence"].update(expires="not-a-date"),
            "must be an ISO calendar date",
        ),
        (
            lambda raw: raw["evidence"].update(expires="20300101"),
            "must be an ISO calendar date",
        ),
    ],
)
def test_invalid_semantic_shapes_are_typed_and_value_safe(mutate, message: str) -> None:
    raw = raw_fixture()
    mutate(raw)

    with pytest.raises(InventoryFormatError, match=message) as caught:
        DynamicInventory.from_json(encoded(raw))

    assert "unsafe" not in str(caught.value)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{", "not valid JSON at line 1 column 2"),
        ("NaN", "not valid JSON"),
        ("[]", "root must be an object"),
        ("{}", "missing field 'inventory_version'"),
        (None, "not valid JSON"),
    ],
)
def test_invalid_roots_use_one_typed_error_boundary(text, message: str) -> None:
    with pytest.raises(InventoryFormatError, match=message):
        DynamicInventory.from_json(text)  # type: ignore[arg-type]


def test_unknown_and_missing_fields_are_rejected() -> None:
    raw = raw_fixture()
    raw["extra"] = "sensitive-value"
    with pytest.raises(InventoryFormatError, match="root has unknown field 'extra'") as caught:
        DynamicInventory.from_json(encoded(raw))
    assert "sensitive-value" not in str(caught.value)

    raw = raw_fixture()
    del raw["source"]["producer"]
    with pytest.raises(InventoryFormatError, match="source is missing field 'producer'"):
        DynamicInventory.from_json(encoded(raw))


def test_records_must_be_objects() -> None:
    for field in ("boundary", "source", "membership", "evidence"):
        raw = raw_fixture()
        raw[field] = []
        with pytest.raises(InventoryFormatError, match=f"{field} must be an object"):
            DynamicInventory.from_json(encoded(raw))

    raw = raw_fixture()
    raw["boundary"]["target"] = []
    with pytest.raises(InventoryFormatError, match="boundary.target must be an object"):
        DynamicInventory.from_json(encoded(raw))


def test_unreviewed_evidence_has_no_clock_fields() -> None:
    raw = raw_fixture()
    raw["evidence"] = {
        "confidence": "unknown",
        "review": "unreviewed",
        "reviewer": None,
        "expires": None,
    }

    evidence = DynamicInventory.from_json(encoded(raw)).evidence

    assert evidence.reviewer is None
    assert evidence.expires is None
