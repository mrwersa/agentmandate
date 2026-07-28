from decimal import Decimal

import pytest

from agentmandate import Mandate, ManifestError, loads
from agentmandate.manifest import CALLER, IRREVERSIBLE, Money, load

MINIMAL = """
{"agent": "a", "tools": [{"name": "t", "effect": "read"}]}
"""


def test_json_manifest_parses_without_yaml():
    mandate = loads(MINIMAL)
    assert mandate.agent == "a"
    assert mandate.tool_names == ("t",)
    assert mandate.tool("t").principal == CALLER
    assert mandate.tool("missing") is None


def test_yaml_manifest_parses():
    mandate = loads("agent: a\ntools:\n  - name: t\n    effect: read\n")
    assert mandate.tool_names == ("t",)


def test_load_reads_from_disk(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(MINIMAL, encoding="utf-8")
    assert load(path).agent == "a"
    assert load(path).source == str(path)


def test_load_reports_a_missing_file(tmp_path):
    with pytest.raises(ManifestError, match="cannot read manifest"):
        load(tmp_path / "absent.yaml")


@pytest.mark.parametrize(
    "body, message",
    [
        ("[]", "expected a mapping"),
        ('{"agent": "a", "tools": []}', "non-empty list"),
        ('{"tools": [{"name": "t", "effect": "read"}]}', "agent is required"),
        ('{"agent": "a", "version": 9, "tools": [{"name": "t"}]}', "schema version"),
        ('{"agent": "a", "tools": [{"effect": "read"}]}', "name is required"),
        ('{"agent": "a", "tools": [{"name": "t", "effect": "nope"}]}', "effect must be"),
        (
            '{"agent": "a", "tools": [{"name": "t", "effect": "read", "principal": "x"}]}',
            "principal must be",
        ),
        (
            '{"agent": "a", "tools": [{"name": "t", "effect": "read"},'
            ' {"name": "t", "effect": "read"}]}',
            "duplicate tool",
        ),
        (
            '{"agent": "a", "tools": [{"name": "t", "effect": "read", "requires": 5}]}',
            "requires must be",
        ),
        (
            '{"agent": "a", "tools": [{"name": "t", "effect": "read", "produces": 5}]}',
            "produces must be",
        ),
        ('{"agent": "a", "tools": ["t"]}', "expected a mapping"),
        ('{"agent": "a", "identity": 5, "tools": [{"name": "t", "effect": "read"}]}', "identity"),
        (
            '{"agent": "a", "limits": {"depth": 0},'
            ' "tools": [{"name": "t", "effect": "read"}]}',
            "positive integer",
        ),
        (
            '{"agent": "a", "limits": [], "tools": [{"name": "t", "effect": "read"}]}',
            "limits: expected a mapping",
        ),
        (
            '{"agent": "a", "roles": {"proposer": ["nope"]},'
            ' "tools": [{"name": "t", "effect": "read"}]}',
            "unknown tool",
        ),
        (
            '{"agent": "a", "roles": {"proposer": 5},'
            ' "tools": [{"name": "t", "effect": "read"}]}',
            "expected a list",
        ),
        (
            '{"agent": "a", "roles": [], "tools": [{"name": "t", "effect": "read"}]}',
            "roles: expected a mapping",
        ),
    ],
)
def test_malformed_manifests_are_rejected(body, message):
    with pytest.raises(ManifestError, match=message):
        loads(body)


def test_ceiling_requires_a_value_argument():
    with pytest.raises(ManifestError, match="declared together"):
        loads(
            '{"agent": "a", "tools": [{"name": "t", "effect": "write",'
            ' "ceiling": {"amount": 1, "currency": "GBP"}}]}'
        )


def test_ceiling_requires_a_scope_key():
    with pytest.raises(ManifestError, match="scope_key is required"):
        loads(
            '{"agent": "a", "tools": [{"name": "t", "effect": "write",'
            ' "value_arg": "amount", "ceiling": {"amount": 1, "currency": "GBP"}}]}'
        )


def test_value_arg_must_be_a_string():
    with pytest.raises(ManifestError, match="value_arg must be"):
        loads(
            '{"agent": "a", "tools": [{"name": "t", "effect": "write",'
            ' "value_arg": 5, "ceiling": {"amount": 1, "currency": "GBP"}}]}'
        )


def test_scope_key_must_be_a_string():
    with pytest.raises(ManifestError, match="scope_key must be"):
        loads(
            '{"agent": "a", "tools": [{"name": "t", "effect": "write",'
            ' "value_arg": "amount", "scope_key": 5,'
            ' "ceiling": {"amount": 1, "currency": "GBP"}}]}'
        )


@pytest.mark.parametrize(
    "raw, message",
    [
        ("nope", "expected a mapping"),
        ({"amount": 1}, "missing currency"),
        ({"amount": "x", "currency": "GBP"}, "not a number"),
        ({"amount": -1, "currency": "GBP"}, "must not be negative"),
        ({"amount": 1, "currency": "POUNDS"}, "three-letter"),
    ],
)
def test_money_validation(raw, message):
    with pytest.raises(ManifestError, match=message):
        Money.parse(raw, "where")


def test_money_uses_decimal_so_sums_are_exact():
    money = Money.parse({"amount": "0.1", "currency": "gbp"}, "w")
    assert money.amount == Decimal("0.1")
    assert money.currency == "GBP"
    assert str(money) == "0.1 GBP"


def test_requires_accepts_a_bare_string():
    mandate = loads(
        '{"agent": "a", "tools": [{"name": "t", "effect": "read", "requires": "case"}]}'
    )
    assert mandate.tool("t").requires == ("case",)


def test_roles_accept_a_bare_string():
    mandate = loads(
        '{"agent": "a", "roles": {"proposer": "t"},'
        ' "tools": [{"name": "t", "effect": "read"}]}'
    )
    assert mandate.roles["proposer"] == ("t",)


def test_spends_value_reflects_a_complete_ceiling():
    mandate = Mandate.parse(
        {
            "agent": "a",
            "tools": [
                {
                    "name": "pay",
                    "effect": IRREVERSIBLE,
                    "requires": ["case"],
                    "value_arg": "amount",
                    "scope_key": "case",
                    "ceiling": {"amount": 10, "currency": "GBP"},
                },
                {"name": "look", "effect": "read"},
            ],
        }
    )
    assert mandate.tool("pay").spends_value is True
    assert mandate.tool("look").spends_value is False
