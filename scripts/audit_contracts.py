"""Check the checkout contract inventory; never rewrite its baseline."""

from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests/fixtures/current-contract-inventory.json"
COVERAGE = ROOT / "tests/fixtures/contract-coverage.json"
sys.path.insert(0, str(ROOT))

import agentmandate  # noqa: E402
from agentmandate.cli import build_parser  # noqa: E402


def python_surface():
    unlisted = {
        name
        for name, value in vars(agentmandate).items()
        if not name.startswith("_")
        and not inspect.ismodule(value)
        and name != "annotations"
        and name not in agentmandate.__all__
    }
    if unlisted:
        raise ValueError(f"unlisted root exports: {', '.join(sorted(unlisted))}")
    result = {}
    for name in sorted(agentmandate.__all__):
        value = getattr(agentmandate, name)
        if name == "__version__":
            result[name] = {"kind": "release-version"}
        elif callable(value):
            try:
                signature = str(inspect.signature(value))
            except ValueError:  # Built-in exception constructors have no signature.
                signature = None
            row = {
                "kind": "class" if inspect.isclass(value) else "function",
                "signature": signature,
            }
            if inspect.isclass(value):
                row["bases"] = [base.__name__ for base in value.__bases__]
                row["members"] = {
                    member_name: {
                        "kind": type(member).__name__,
                        "signature": str(
                            inspect.signature(
                                member.fget
                                if isinstance(member, property)
                                else getattr(value, member_name)
                            )
                        ),
                    }
                    for member_name, member in sorted(vars(value).items())
                    if not member_name.startswith("_")
                    and (
                        isinstance(member, (property, classmethod, staticmethod))
                        or inspect.isfunction(member)
                    )
                }
            result[name] = row
        else:
            result[name] = {"kind": "constant", "value": value}
    return result


def cli_surface(parser=None, path="mandate"):
    parser = build_parser() if parser is None else parser
    arguments = []
    children = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            arguments.append(
                {
                    "dest": action.dest,
                    "action": type(action).__name__,
                    "required": action.required,
                    "choices": sorted(action.choices),
                }
            )
            for name, child in sorted(action.choices.items()):
                children.update(cli_surface(child, f"{path} {name}"))
        else:
            arguments.append(
                {
                    "dest": action.dest,
                    "options": action.option_strings,
                    "action": type(action).__name__,
                    "nargs": action.nargs,
                    "required": action.required,
                    "default": action.default,
                    "choices": None if action.choices is None else list(action.choices),
                    "type": None if action.type is None else action.type.__name__,
                }
            )
    groups = [
        {"required": group.required, "members": [a.dest for a in group._group_actions]}
        for group in parser._mutually_exclusive_groups
    ]
    return {path: {"arguments": arguments, "exclusive_groups": groups}, **children}


def artifact_markers(directory=None):
    """Inventory declarations, not the full semantics of each validator."""
    directory = ROOT / "agentmandate" if directory is None else directory
    result = {}
    for path in sorted(directory.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.endswith(("_VERSION", "_SCHEMA")):
                        constants[target.id] = node.value.value
        strings = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        schemas = sorted(
            s for s in strings if re.fullmatch(r"agent(?:mandate|verity)\.[\w.-]+/v\d+", s)
        )
        fields = sorted(s for s in strings if re.fullmatch(r"[a-z_]+_version", s))
        inline_versions = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                names = {
                    item.value
                    for item in ast.walk(node.left)
                    if isinstance(item, ast.Constant) and item.value in fields
                }
                for value in node.comparators:
                    if isinstance(value, ast.Constant) and type(value.value) is int:
                        for name in names:
                            inline_versions.setdefault(name, set()).add(value.value)
        if constants or schemas or fields:
            result[path.name] = {
                "constants": constants,
                "schemas": schemas,
                "version_fields": fields,
                "inline_versions": {k: sorted(v) for k, v in sorted(inline_versions.items())},
            }
    return result


def snapshot(coverage=None):
    coverage = json.loads(COVERAGE.read_text()) if coverage is None else coverage
    files = sorted({path for row in coverage for path in row["fixtures"]})
    return {
        "coverage_sha256": hashlib.sha256(
            json.dumps(coverage, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "public_python": python_surface(),
        "cli": cli_surface(),
        "artifact_markers": artifact_markers(),
        "fixture_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in files
        },
    }


def differences(expected, actual, path=""):
    """Return useful leaf locations, including removed or newly added records."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        result = []
        for key in sorted(expected.keys() | actual.keys()):
            location = f"{path}/{key}"
            if key not in expected or key not in actual:
                result.append(location)
            else:
                result.extend(differences(expected[key], actual[key], location))
        return result
    return [] if expected == actual else [path]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, help="write a separate candidate for review")
    args = parser.parse_args(argv)
    if args.candidate is not None and args.candidate.resolve() in {
        BASELINE.resolve(),
        COVERAGE.resolve(),
    }:
        parser.error("candidate must not overwrite the inventory or coverage baseline")
    try:
        current = snapshot()
        if args.candidate is not None:
            args.candidate.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
            return 0
        expected = json.loads(BASELINE.read_text())
        if not isinstance(expected, dict) or expected.keys() != current.keys():
            raise ValueError("inventory baseline has unsupported fields or shape")
        if any(not isinstance(expected[key], dict) for key in current if key != "coverage_sha256"):
            raise ValueError("inventory baseline sections must be objects")
        changed = differences(expected, current)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if changed:
        print("Contract inventory changed; review compatibility before replacing the baseline:")
        print("\n".join(changed))
        return 1
    print(
        f"Contract inventory matches: {len(current['public_python'])} Python exports, "
        f"{len(current['cli'])} command paths, {len(current['fixture_sha256'])} pinned files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
