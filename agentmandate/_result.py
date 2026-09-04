"""Shared validation primitives for private analysis-result envelopes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def validate_authority(
    value: Any,
    *,
    error_type: type[ValueError],
    result_name: str,
    whitespace_term: str,
) -> dict[str, Any]:
    """Validate the Authority mapping embedded in a result envelope."""

    def fail(message: str) -> None:
        raise error_type(f"{result_name} {message}")

    def record(item: Any, path: str, fields: set[str]) -> dict[str, Any]:
        if not isinstance(item, dict):
            fail(f"{path} must be an object")
        missing = sorted(fields - item.keys())
        if missing:
            fail(f"{path} is missing field {missing[0]!r}")
        extra = sorted(item.keys() - fields)
        if extra:
            fail(f"{path} has unknown field {extra[0]!r}")
        return item

    def string(item: Any, path: str) -> str:
        if not isinstance(item, str) or not item or item != item.strip():
            fail(f"{path} must be a non-empty {whitespace_term} string")
        return item

    def strings(item: Any, path: str) -> tuple[str, ...]:
        if not isinstance(item, list):
            fail(f"{path} must be an array")
        parsed = tuple(string(member, f"{path}/{index}") for index, member in enumerate(item))
        if list(parsed) != sorted(set(parsed)):
            fail(f"{path} must contain sorted unique strings")
        return parsed

    fields = {
        "reachable_tools",
        "effects",
        "ungated_irreversible",
        "service_principal_tools",
        "max_extractable",
        "breaches",
        "depth",
        "truncated",
    }
    authority = record(value, "/authority", fields)
    for field in ("reachable_tools", "ungated_irreversible", "service_principal_tools"):
        strings(authority[field], f"/authority/{field}")

    effects = authority["effects"]
    if not isinstance(effects, list) or any(
        not isinstance(pair, list) or len(pair) != 2 for pair in effects
    ):
        fail("/authority/effects must contain string pairs")
    pairs = [
        tuple(string(item, f"/authority/effects/{index}/{part}") for part, item in enumerate(pair))
        for index, pair in enumerate(effects)
    ]
    if pairs != sorted(set(pairs)):
        fail("/authority/effects must be sorted and unique")

    maximum = authority["max_extractable"]
    if maximum is not None:
        money = record(maximum, "/authority/max_extractable", {"amount", "currency"})
        amount = string(money["amount"], "/authority/max_extractable/amount")
        try:
            parsed = Decimal(amount)
        except InvalidOperation as exc:
            raise error_type(
                f"{result_name} /authority/max_extractable/amount must be decimal"
            ) from exc
        if not parsed.is_finite() or str(parsed) != amount:
            fail("/authority/max_extractable/amount must be canonical")
        string(money["currency"], "/authority/max_extractable/currency")

    breaches = authority["breaches"]
    if not isinstance(breaches, list):
        fail("/authority/breaches must be an array")
    for index, item in enumerate(breaches):
        breach = record(item, f"/authority/breaches/{index}", {"kind", "detail", "path"})
        string(breach["kind"], f"/authority/breaches/{index}/kind")
        string(breach["detail"], f"/authority/breaches/{index}/detail")
        path = breach["path"]
        if not isinstance(path, list) or not path:
            fail(f"/authority/breaches/{index}/path must be non-empty array")
        for step, rendered in enumerate(path):
            string(rendered, f"/authority/breaches/{index}/path/{step}")

    if type(authority["depth"]) is not int or authority["depth"] < 0:
        fail("/authority/depth must be a non-negative integer")
    if type(authority["truncated"]) is not bool:
        fail("/authority/truncated must be a boolean")
    return authority
