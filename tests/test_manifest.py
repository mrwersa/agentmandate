from decimal import Decimal

import pytest

from agentmandate import Mandate, ManifestError, loads
from agentmandate.manifest import CALLER, IRREVERSIBLE, Quantity, load

MINIMAL = '{"agent": "a", "tools": [{"name": "t", "effect": "read"}], "version": 2}'


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
        ('{"agent": "a", "tools": [], "version": 2}', "non-empty list"),
        ('{"tools": [{"name": "t", "effect": "read"}]}', "agent must be a non-empty string"),
        ('{"agent": "a", "version": 99, "tools": [{"name": "t"}]}', "schema version"),
        (
            '{"agent": "a", "tools": [{"effect": "read"}], "version": 2}',
            "name must be a non-empty string",
        ),
        (
            '{"agent": "a", "tools": [{"name": "t", "effect": "nope"}], "version": 2}',
            "effect must be",
        ),
        (
            (
                '{"agent": "a", "tools": [{"name": "t", "effect": "read", "princi'
                'pal": "x"}], "version": 2}'
            ),
            "principal must be",
        ),
        (
            (
                '{"agent": "a", "tools": [{"name": "t", "effect": "read"}, {"name'
                '": "t", "effect": "read"}], "version": 2}'
            ),
            "duplicate tool",
        ),
        (
            (
                '{"agent": "a", "tools": [{"name": "t", "effect": "read", "requir'
                'es": 5}], "version": 2}'
            ),
            "requires must be",
        ),
        (
            (
                '{"agent": "a", "tools": [{"name": "t", "effect": "read", "produc'
                'es": 5}], "version": 2}'
            ),
            "produces must be",
        ),
        ('{"agent": "a", "tools": ["t"], "version": 2}', "expected a mapping"),
        (
            (
                '{"agent": "a", "identity": 5, "tools": [{"name": "t", "effect": '
                '"read"}], "version": 2}'
            ),
            "identity",
        ),
        (
            (
                '{"agent": "a", "limits": {"depth": 0}, "tools": [{"name": "t", "'
                'effect": "read"}], "version": 2}'
            ),
            "positive integer",
        ),
        (
            (
                '{"agent": "a", "limits": [], "tools": [{"name": "t", "effect": "'
                'read"}], "version": 2}'
            ),
            "limits: expected a mapping",
        ),
        (
            (
                '{"agent": "a", "roles": {"proposer": ["nope"]}, "tools": [{"name'
                '": "t", "effect": "read"}], "version": 2}'
            ),
            "unknown tool",
        ),
        (
            (
                '{"agent": "a", "roles": {"proposer": 5}, "tools": [{"name": "t",'
                ' "effect": "read"}], "version": 2}'
            ),
            "expected a list",
        ),
        (
            '{"agent": "a", "roles": [], "tools": [{"name": "t", "effect": "read"}], "version": 2}',
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
            '{"agent": "a", "tools": [{"name": "t", "effect": "write", "ceili'
            'ng": {"amount": 1, "unit": "GBP"}, "quantity": "value"}], "versi'
            'on": 2}'
        )


def test_ceiling_requires_a_scope_key():
    with pytest.raises(ManifestError, match="scope_key is required"):
        loads(
            '{"agent": "a", "tools": [{"name": "t", "effect": "write", "value'
            '_arg": "amount", "ceiling": {"amount": 1, "unit": "GBP"}, "quant'
            'ity": "value"}], "version": 2}'
        )


def test_value_arg_must_be_a_string():
    with pytest.raises(ManifestError, match="value_arg must be"):
        loads(
            '{"agent": "a", "tools": [{"name": "t", "effect": "write", "value'
            '_arg": 5, "ceiling": {"amount": 1, "unit": "GBP"}, "quantity": "'
            'value"}], "version": 2}'
        )


def test_scope_key_must_be_a_string():
    with pytest.raises(ManifestError, match="scope_key must be"):
        loads(
            '{"agent": "a", "tools": [{"name": "t", "effect": "write", "value'
            '_arg": "amount", "scope_key": 5, "ceiling": {"amount": 1, "unit"'
            ': "GBP"}, "quantity": "value"}], "version": 2}'
        )


@pytest.mark.parametrize(
    "raw, message",
    [
        ("nope", "expected a mapping"),
        ({"amount": 1}, "missing unit"),
        ({"amount": "x", "unit": "GBP"}, "not a number"),
        ({"amount": "NaN", "unit": "GBP"}, "must be finite"),
        ({"amount": "Infinity", "unit": "GBP"}, "must be finite"),
        ({"amount": -1, "unit": "GBP"}, "must not be negative"),
        ({"amount": 1, "unit": ""}, "non-empty"),
        ({"amount": 1, "unit": 123}, "non-empty"),
        ({"amount": 1, "unit": " record "}, "whitespace"),
    ],
)
def test_quantity_validation(raw, message):
    with pytest.raises(ManifestError, match=message):
        Quantity.parse(raw, "where")


def test_quantity_uses_decimal_so_sums_are_exact():
    money = Quantity.parse({"amount": "0.1", "unit": "gbp"}, "w")
    assert money.amount == Decimal("0.1")
    assert money.unit == "gbp"
    assert str(money) == "0.1 gbp"


def test_requires_accepts_a_bare_string():
    mandate = loads(
        '{"agent": "a", "tools": [{"name": "t", "effect": "read", "requir'
        'es": "case"}], "version": 2}'
    )
    assert mandate.tool("t").requires == ("case",)


def test_roles_accept_a_bare_string():
    mandate = loads(
        '{"agent": "a", "roles": {"proposer": "t"}, "tools": [{"name": "t'
        '", "effect": "read"}], "version": 2}'
    )
    assert mandate.roles["proposer"] == ("t",)


def test_spends_value_reflects_a_complete_ceiling():
    mandate = Mandate.parse(
        {
            "agent": "a",
            "tools": [
                {
                    "quantity": "value",
                    "name": "pay",
                    "effect": IRREVERSIBLE,
                    "requires": ["case"],
                    "value_arg": "amount",
                    "scope_key": "case",
                    "ceiling": {"amount": 10, "unit": "GBP"},
                },
                {"name": "look", "effect": "read"},
            ],
        }
    )
    assert mandate.tool("pay").spends_value is True
    assert mandate.tool("look").spends_value is False


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("unbounded", "false", "unbounded must be true or false"),
        ("requires_approval", "false", "requires_approval must be true or false"),
    ],
)
def test_boolean_fields_do_not_coerce_strings(field, value, message):
    with pytest.raises(ManifestError, match=message):
        Mandate.parse(
            {
                "agent": "a",
                "tools": [{"name": "t", "effect": "read", field: value}],
            }
        )


def test_boolean_depth_is_not_an_integer():
    with pytest.raises(ManifestError, match="positive integer"):
        loads(
            '{"agent": "a", "limits": {"depth": true}, "tools": [{"name": "t"'
            ', "effect": "read"}], "version": 2}'
        )


def test_empty_scope_names_are_rejected():
    with pytest.raises(ManifestError, match="requires must be"):
        loads(
            '{"agent": "a", "tools": [{"name": "t", "effect": "read", "requir'
            'es": [""]}], "version": 2}'
        )


@pytest.mark.parametrize("body, message", [("{bad", "invalid JSON"), ("agent: [", "invalid YAML")])
def test_parser_errors_are_wrapped_as_manifest_errors(body, message):
    with pytest.raises(ManifestError, match=message):
        loads(body)


def test_a_tool_name_with_a_control_character_is_rejected():
    with pytest.raises(ManifestError, match="must not contain control characters"):
        loads('{"agent": "a", "tools": [{"name": "t\\nx", "effect": "read"}], "version": 2}')
