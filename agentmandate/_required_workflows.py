"""Caller-authored positive paths, checked only against the manifest-v2 model."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext

from .manifest import Mandate, Quantity
from .reach import _arithmetic_context

REQUIRED_WORKFLOWS_SCHEMA = "agentmandate.required-workflows/v2"


def _object(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional):
        raise ValueError("required-workflow record has unsupported fields or shape")
    if set(required) - set(value):
        raise ValueError("required-workflow record is missing required fields")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\x00"):
        raise ValueError("required-workflow names and annotations must be nonblank strings")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate required-workflow field {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True)
class _Call:
    tool: str
    principal: str
    approved: bool
    binding: int | None
    value: Quantity | None
    quantity: str | None

    @classmethod
    def parse(cls, raw):
        raw = _object(
            raw, ("tool", "principal", "approved"), ("binding", "value", "unit", "quantity")
        )
        if type(raw["approved"]) is not bool:
            raise ValueError("required-workflow approved must be true or false")
        binding = raw.get("binding")
        if binding is not None and (type(binding) is not int or binding < 0):
            raise ValueError("required-workflow binding must be a nonnegative integer")
        value = None
        if any(name in raw for name in ("value", "unit", "quantity")):
            if not isinstance(raw.get("value"), str) or "unit" not in raw or "quantity" not in raw:
                raise ValueError("required-workflow value must be a string with quantity and unit")
            value = Quantity.parse(
                {"amount": raw["value"], "unit": raw["unit"]}, "required-workflow value"
            )
        return cls(
            _text(raw["tool"]),
            _text(raw["principal"]),
            raw["approved"],
            binding,
            value,
            _text(raw["quantity"]) if value is not None else None,
        )


@dataclass(frozen=True)
class _Workflow:
    name: str
    steps: tuple[_Call, ...]

    @classmethod
    def parse(cls, raw):
        raw = _object(raw, ("name", "steps"))
        if not isinstance(raw["steps"], list) or not raw["steps"]:
            raise ValueError("required workflow must have a nonempty steps list")
        return cls(_text(raw["name"]), tuple(_Call.parse(step) for step in raw["steps"]))


@dataclass(frozen=True)
class _Requirements:
    agent: str
    manifest_sha256: str
    reviewer: str
    reason: str
    workflows: tuple[_Workflow, ...]
    source_sha256: str

    @classmethod
    def load(cls, content: bytes, mandate: Mandate, manifest_sha256: str):
        raw = _object(
            json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object),
            ("schema", "agent", "manifest_sha256", "reviewer", "reason", "workflows"),
        )
        if raw["schema"] != REQUIRED_WORKFLOWS_SCHEMA:
            raise ValueError("unsupported required-workflows schema")
        agent = _text(raw["agent"])
        digest = _text(raw["manifest_sha256"])
        if not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("required-workflow manifest_sha256 must be lowercase SHA-256")
        if agent != mandate.agent or digest != manifest_sha256:
            raise ValueError("required workflows do not match the exact baseline manifest")
        if not isinstance(raw["workflows"], list) or not raw["workflows"]:
            raise ValueError("required-workflows input must name at least one workflow")
        workflows = tuple(_Workflow.parse(row) for row in raw["workflows"])
        if len({row.name for row in workflows}) != len(workflows):
            raise ValueError("required-workflow names must be unique")
        return cls(
            agent,
            digest,
            _text(raw["reviewer"]),
            _text(raw["reason"]),
            workflows,
            hashlib.sha256(content).hexdigest(),
        )

    def metadata(self):
        return {
            "schema": REQUIRED_WORKFLOWS_SCHEMA,
            "source_sha256": self.source_sha256,
            "manifest_sha256": self.manifest_sha256,
            "agent": self.agent,
            "reviewer": self.reviewer,
            "reason": self.reason,
            "scope": "caller-supplied annotations; manifest-v2 model only, not business success",
        }

    def assess(self, mandate: Mandate, depth: int):
        return [_assessment(mandate, workflow, depth) for workflow in self.workflows]


def _failure(step, rule, detail):
    return {"step": step, "rule": rule, "detail": detail}


def _assessment(mandate, workflow, depth):
    amounts = [t.ceiling.amount for t in mandate.tools if t.ceiling]
    amounts.extend(step.value.amount for step in workflow.steps if step.value is not None)
    try:
        with localcontext(_arithmetic_context(amounts, len(workflow.steps))):
            failure = _check(mandate, workflow.steps, depth)
    except (DecimalException, ValueError) as exc:
        raise ValueError(
            "required-workflow amounts exceed supported exact decimal arithmetic"
        ) from exc
    return {
        "name": workflow.name,
        "steps": len(workflow.steps),
        "status": "conformant_within_manifest_model"
        if failure is None
        else "not_conformant_within_manifest_model",
        "failure": failure,
    }


def _check(mandate, steps, depth):
    if len(steps) > depth:
        return _failure(0, "workflow.depth-exceeded", "path exceeds the selected search depth")
    counts = {}
    spend = {}
    effects = {}
    totals = {}
    for index, step in enumerate(steps, 1):
        tool = mandate.tool(step.tool)
        if tool is None:
            return _failure(index, "workflow.undeclared-tool", f"tool {step.tool!r} is absent")
        if any(counts.get(scope, 0) == 0 for scope in tool.requires):
            return _failure(
                index, "workflow.scope-unavailable", "a required scope has not been produced"
            )
        if tool.principal != step.principal:
            return _failure(
                index, "workflow.principal-mismatch", "call principal differs from the declaration"
            )
        if tool.requires_approval and not step.approved:
            return _failure(index, "workflow.approval-missing", "call lacks required approval")
        # Production precedes spending in the search, including a tool that does both.
        if tool.produces and (tool.unbounded or counts.get(tool.produces, 0) == 0):
            counts[tool.produces] = counts.get(tool.produces, 0) + 1
        effects[tool.effect] = effects.get(tool.effect, 0) + 1
        if (
            tool.effect in mandate.limits.effects
            and effects[tool.effect] > mandate.limits.effects[tool.effect]
        ):
            return _failure(
                index, "workflow.effect-budget-exceeded", "call count exceeds its effect budget"
            )
        if not tool.spends_value:
            if step.value is not None or step.binding is not None:
                return _failure(
                    index, "workflow.unexpected-spend", "nonspending call has quantity fields"
                )
            continue
        if step.value is None or step.binding is None:
            return _failure(
                index,
                "workflow.spend-missing",
                "spending call needs value, quantity, unit and binding",
            )
        if step.binding >= counts.get(tool.scope_key, 0):
            return _failure(
                index, "workflow.binding-unavailable", "the selected binding has not been produced"
            )
        cap = mandate.limits.quantities.get(tool.quantity)
        if (
            step.quantity != tool.quantity
            or step.value.unit != tool.ceiling.unit
            or (cap is not None and step.value.unit != cap.unit)
        ):
            return _failure(
                index,
                "workflow.unit-mismatch",
                "call and ceiling use different quantities or units",
            )
        key = (tool.name, tool.scope_key, step.binding)
        spend[key] = spend.get(key, Decimal(0)) + step.value.amount
        if spend[key] > tool.ceiling.amount:
            return _failure(
                index,
                "workflow.ceiling-exceeded",
                "cumulative value exceeds the per-binding ceiling",
            )
        name = tool.quantity
        totals[name] = totals.get(name, Decimal(0)) + step.value.amount
        cap = mandate.limits.quantities.get(name)
        if cap is not None and totals[name] > cap.amount:
            return _failure(
                index,
                "workflow.quantity-exceeded",
                f"cumulative quantity {name!r} exceeds its budget",
            )
    return None
