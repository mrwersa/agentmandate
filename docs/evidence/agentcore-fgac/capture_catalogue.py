"""Derive the source-side AgentCore tool mapping without importing upstream code."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
INDEX = ROOT / "source-index.json"
ROUTES = (
    ("upstream/products.py.txt", "/products"),
    ("upstream/cart.py.txt", "/cart"),
    ("upstream/checkout.py.txt", ""),
    ("upstream/main.py.txt", ""),
)
METHODS = frozenset({"get", "patch", "post"})


def _verify_sources() -> dict[str, Any]:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    for source in index["sources"]:
        content = (ROOT / source["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != source["sha256"]:
            raise ValueError(f"source digest mismatch: {source['path']}")
    return index


def _route(
    decorator: ast.Call, function: ast.FunctionDef, prefix: str, source: str
) -> dict[str, Any]:
    method = decorator.func.attr
    path = decorator.args[0].value
    operation_id = next(
        (
            keyword.value.value
            for keyword in decorator.keywords
            if keyword.arg == "operation_id" and isinstance(keyword.value, ast.Constant)
        ),
        None,
    )
    annotations = {
        argument.annotation.id
        for argument in function.args.args
        if isinstance(argument.annotation, ast.Name)
    }
    backend_access = (
        "admin_only"
        if "AdminDep" in annotations
        else "authenticated"
        if "PrincipalDep" in annotations
        else "public"
    )
    return {
        "action": None if operation_id is None else f"ecommerce-tools___{operation_id}",
        "backend_access": backend_access,
        "line": function.lineno,
        "method": method.upper(),
        "operation_id": operation_id,
        "path": f"{prefix}{path}",
        "source": source,
    }


def capture() -> dict[str, Any]:
    index = _verify_sources()
    routes: list[dict[str, Any]] = []
    for source, prefix in ROUTES:
        tree = ast.parse((ROOT / source).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for raw in node.decorator_list:
                if (
                    isinstance(raw, ast.Call)
                    and isinstance(raw.func, ast.Attribute)
                    and raw.func.attr in METHODS
                    and raw.args
                    and isinstance(raw.args[0], ast.Constant)
                    and isinstance(raw.args[0].value, str)
                ):
                    routes.append(_route(raw, node, prefix, source))
    terraform = (ROOT / "upstream/agentcore-main.tf").read_text(encoding="utf-8")
    target = re.search(r'name\s+=\s+"(ecommerce-tools)"', terraform)
    if target is None:
        raise ValueError("Gateway target name is absent")
    readme = (ROOT / "upstream/upstream-README.md").read_text(encoding="utf-8")
    customer_policy = re.search(
        r'--name "ecommerce_customer_access"(?P<body>.*?)--validation-mode',
        readme,
        re.DOTALL,
    )
    if customer_policy is None:
        raise ValueError("customer Cedar policy is absent")
    customer_actions = sorted(
        set(re.findall(r'ecommerce-tools___([a-z_]+)', customer_policy.group("body")))
    )
    for route in routes:
        route["cedar_admin"] = "allow"
        route["cedar_customer"] = (
            "allow" if route["operation_id"] in customer_actions else "deny"
        )
    explicit = sorted(route["operation_id"] for route in routes if route["operation_id"])
    return {
        "catalogue_version": 1,
        "mapping_complete": False,
        "revision": index["revision"],
        "routes": sorted(routes, key=lambda item: (item["path"], item["method"])),
        "source_declared_operation_ids": explicit,
        "source_route_count": len(routes),
        "target": target.group(1),
        "unresolved": [
            "GET /health has no explicit operation_id; the generated Gateway tool name "
            "is not captured",
            "native AgentCore tools/list and ENFORCE decision records are absent",
        ],
        "customer_policy_actions": customer_actions,
    }


def main() -> None:
    print(json.dumps(capture(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
