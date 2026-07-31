"""Derive a manifest skeleton from agent source code.

``scan`` reads an MCP ``tools/list`` catalogue, which a team only has if they
run an MCP server. Most agents declare their tools in Python, with a decorator
and a list passed to an agent constructor, and those teams could not get a
starting manifest at all.

This reads that source without importing it. Nothing here executes the agent,
installs its framework, or resolves its imports. That is a deliberate limit
rather than a shortcut: the command is meant to run in a review, on a branch,
against code whose dependencies are not installed and whose side effects
should not happen.

What a decorator carries is a name, a docstring, and a signature. What a
mandate needs is whether the effect is reversible, which argument spends
value, and what a ceiling is measured against, and no parsing recovers those.
So this feeds the same conservative proposals as ``scan``, with a ``REVIEW``
marker on every guess.

The second thing it reports is what it could not see. An agent assembled from
``tools=get_tools()`` has an inventory this cannot enumerate, and a manifest
that silently omits those tools is worse than no manifest, because the diff
against the next release would call them new.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .scan import Proposal, _effect_for, _scope_for, _value_arg_for

# Decorators that declare a callable as an agent tool. Matched on the final
# attribute name, because every framework is imported under a different path
# and half of them are aliased at the import site.
#
# - `tool`          LangChain, LangGraph, Strands Agents, CrewAI, FastMCP
# - `function_tool` OpenAI Agents SDK
# - `ai_function`   Microsoft Agent Framework
TOOL_DECORATORS = frozenset({"tool", "function_tool", "ai_function"})

# Keyword arguments through which a framework accepts an explicit tool name,
# overriding the function name.
NAME_KEYWORDS = ("name", "name_override")

# Parameters that carry framework plumbing rather than agent input. Including
# them would invent a scope or a value argument out of a callback handle.
PLUMBING_NAMES = frozenset({"self", "cls", "ctx", "tool_context", "run_context"})
PLUMBING_ANNOTATION_SUFFIXES = ("Context", "ContextWrapper", "ToolContext", "Session")

# Directories that hold installed or generated code rather than the agent.
SKIPPED_DIRECTORIES = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist", ".tox"}
)

# Annotations mapped to the JSON Schema types the shared proposal helpers
# expect. Anything unrecognised stays untyped, which makes the value-argument
# heuristic more cautious rather than less.
ANNOTATION_TYPES = {
    "int": "integer",
    "float": "number",
    "Decimal": "number",
    "complex": "number",
    "str": "string",
    "bool": "boolean",
}


@dataclass(frozen=True)
class Binding:
    """One place the source hands a list of tools to an agent."""

    where: str
    names: tuple[str, ...]
    unresolved: tuple[str, ...]


@dataclass
class Inventory:
    """Everything the source said, and everything it did not say."""

    proposals: list[Proposal] = field(default_factory=list)
    bindings: list[Binding] = field(default_factory=list)
    unbound: list[str] = field(default_factory=list)
    undeclared: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    files_read: int = 0

    @property
    def unresolved(self) -> list[str]:
        """Tool list entries no static read could name."""
        seen: list[str] = []
        for binding in self.bindings:
            for entry in binding.unresolved:
                item = f"{binding.where}: {entry}"
                if item not in seen:
                    seen.append(item)
        return seen


def _decorator_name(node: ast.expr) -> tuple[str | None, ast.Call | None]:
    """Return the trailing name of a decorator and its call, if it has one."""
    call = node if isinstance(node, ast.Call) else None
    target = call.func if call is not None else node
    if isinstance(target, ast.Attribute):
        return target.attr, call
    if isinstance(target, ast.Name):
        return target.id, call
    return None, call


def _declared_name(call: ast.Call | None, fallback: str) -> str:
    """Prefer the name the decorator was given over the function name."""
    if call is None:
        return fallback
    for keyword in call.keywords:
        value = keyword.value
        if (
            keyword.arg in NAME_KEYWORDS
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and value.value.strip()
        ):
            return value.value
    for argument in call.args:
        if (
            isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
            and argument.value.strip()
        ):
            return argument.value
    return fallback


def _annotation_type(annotation: ast.expr | None) -> str | None:
    if annotation is None:
        return None
    if isinstance(annotation, ast.Name):
        return ANNOTATION_TYPES.get(annotation.id)
    if isinstance(annotation, ast.Attribute):
        return ANNOTATION_TYPES.get(annotation.attr)
    if isinstance(annotation, ast.Subscript):
        # `Optional[int]` and `Annotated[float, ...]` still describe a number.
        return _annotation_type(annotation.slice)
    if isinstance(annotation, ast.Tuple) and annotation.elts:
        return _annotation_type(annotation.elts[0])
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return ANNOTATION_TYPES.get(annotation.value)
    return None


def _is_plumbing(name: str, annotation: ast.expr | None) -> bool:
    if name in PLUMBING_NAMES:
        return True
    rendered = ""
    if isinstance(annotation, ast.Name):
        rendered = annotation.id
    elif isinstance(annotation, ast.Attribute):
        rendered = annotation.attr
    elif isinstance(annotation, ast.Subscript):
        inner = annotation.value
        rendered = inner.id if isinstance(inner, ast.Name) else ""
    return rendered.endswith(PLUMBING_ANNOTATION_SUFFIXES)


def _properties(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, dict]:
    """Render the signature as the property map the shared helpers read."""
    arguments = function.args
    ordered = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    properties: dict[str, dict] = {}
    for argument in ordered:
        if _is_plumbing(argument.arg, argument.annotation):
            continue
        spec: dict = {}
        kind = _annotation_type(argument.annotation)
        if kind is not None:
            spec["type"] = kind
        properties[argument.arg] = spec
    return properties


def _description(function: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    docstring = ast.get_docstring(function) or ""
    paragraph = docstring.strip().split("\n\n", 1)[0]
    return " ".join(paragraph.split())


def _entry_name(node: ast.expr) -> str | None:
    """Name a tool list entry, when the entry is a plain reference."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    """Map each renamed import back to the name it was imported under.

    Collected in a pass of its own rather than while walking, so a decorator
    is resolved the same way whatever order the file puts things in.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name.rsplit(".", 1)[-1]
    return aliases


class _Reader(ast.NodeVisitor):
    """Collect tool definitions and tool bindings from one module."""

    def __init__(self, where: str, aliases: dict[str, str]) -> None:
        self.where = where
        # `from strands import tool as strands_tool` is common enough that
        # matching the decorator name alone misses the declaration entirely.
        self.aliases = aliases
        self.definitions: dict[str, Proposal] = {}
        # The identifier the tool is referenced by in a `tools=[...]` list is
        # the function name, which is not always the declared tool name.
        self.symbols: dict[str, str] = {}
        self.bindings: list[Binding] = []

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for decorator in node.decorator_list:
            name, call = _decorator_name(decorator)
            if name is not None:
                name = self.aliases.get(name, name)
            if name not in TOOL_DECORATORS:
                continue
            declared = _declared_name(call, node.name)
            effect, guessed = _effect_for(declared)
            properties = _properties(node)
            self.definitions[declared] = Proposal(
                name=declared,
                effect=effect,
                guessed_effect=guessed,
                scope=_scope_for(properties),
                value_arg=_value_arg_for(properties),
                description=_description(node),
            )
            self.symbols[node.name] = declared
            break
        self.generic_visit(node)

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Call(self, node: ast.Call) -> None:
        listed: ast.expr | None = None
        if isinstance(node.func, ast.Attribute) and node.func.attr == "bind_tools":
            listed = node.args[0] if node.args else None
        else:
            for keyword in node.keywords:
                if keyword.arg == "tools":
                    listed = keyword.value
                    break

        if listed is not None:
            self._record_binding(node, listed)
        self.generic_visit(node)

    def _record_binding(self, call: ast.Call, listed: ast.expr) -> None:
        where = f"{self.where}:{call.lineno}"
        if not isinstance(listed, (ast.List, ast.Tuple, ast.Set)):
            # `tools=get_tools()` or `tools=TOOLS`. The list exists at runtime
            # and this cannot see into it, which is the honest thing to report.
            self.bindings.append(
                Binding(where=where, names=(), unresolved=(ast.unparse(listed),))
            )
            return

        names: list[str] = []
        unresolved: list[str] = []
        for element in listed.elts:
            name = _entry_name(element)
            if name is None:
                unresolved.append(ast.unparse(element))
            else:
                names.append(name)
        self.bindings.append(
            Binding(where=where, names=tuple(names), unresolved=tuple(unresolved))
        )


def _python_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    found: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIPPED_DIRECTORIES for part in path.parts):
            continue
        found.append(path)
    return found


def collect(root: str | Path) -> Inventory:
    """Read tool definitions and bindings from a file or a directory tree."""
    base = Path(root)
    if not base.exists():
        raise ValueError(f"{base} does not exist")

    paths = _python_files(base)
    if not paths:
        raise ValueError(f"{base} contains no Python files")

    inventory = Inventory()
    definitions: dict[str, Proposal] = {}
    symbols: dict[str, str] = {}

    for path in paths:
        where = str(path.relative_to(base) if base.is_dir() else path.name)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            # One unparsable file must not lose the rest of the inventory, but
            # it also must not pass silently: a manifest is being built from
            # what was read, and this file was not read.
            inventory.unreadable.append(f"{where}: {exc.__class__.__name__}")
            continue

        inventory.files_read += 1
        reader = _Reader(where, _import_aliases(tree))
        reader.visit(tree)
        for name, proposal in reader.definitions.items():
            definitions.setdefault(name, proposal)
        symbols.update(reader.symbols)
        inventory.bindings.extend(reader.bindings)

    bound_symbols = {name for binding in inventory.bindings for name in binding.names}
    if bound_symbols:
        # An agent's mandate covers the tools it was given, not every decorated
        # function in the repository.
        resolved = {symbol: symbols.get(symbol, symbol) for symbol in bound_symbols}
        bound_names = {
            name for name in resolved.values() if name in definitions
        }
        inventory.proposals = [
            definitions[name] for name in definitions if name in bound_names
        ]
        inventory.unbound = [name for name in definitions if name not in bound_names]
        # A bound symbol with no declaration in the tree that was read is
        # authority this manifest omits. It is usually a tool imported from a
        # package outside the scanned path, and dropping it quietly is how a
        # manifest ends up describing less than the agent can do.
        inventory.undeclared = sorted(
            symbol for symbol, name in resolved.items() if name not in definitions
        )
    else:
        inventory.proposals = list(definitions.values())

    return inventory


def notes_for(inventory: Inventory) -> list[str]:
    """Turn everything the read could not establish into review lines."""
    notes: list[str] = []

    if not inventory.bindings:
        notes.append(
            "No `tools=[...]` binding was found, so this lists every decorated "
            "tool in the source. A mandate should describe one agent's "
            "authority. Remove any tool this agent is not given."
        )
    elif len(inventory.bindings) > 1:
        sites = ", ".join(binding.where for binding in inventory.bindings)
        notes.append(
            f"{len(inventory.bindings)} tool bindings were found ({sites}). This "
            "manifest is their union. If they are separate agents, give each "
            "one its own manifest, because a union overstates what any single "
            "agent can reach."
        )

    for item in inventory.unresolved:
        notes.append(
            f"A binding passes tools this read cannot enumerate ({item}). Those "
            "tools are missing from the list below, and a later diff would "
            "report them as newly added authority. Add them by hand."
        )

    if inventory.undeclared:
        listed = ", ".join(inventory.undeclared)
        notes.append(
            f"Bound to an agent but declared nowhere in the scanned path: "
            f"{listed}. They are missing from the list below. Widen --source, "
            f"or add them by hand."
        )

    if inventory.unbound:
        listed = ", ".join(sorted(inventory.unbound))
        notes.append(
            f"Defined but not bound to any agent: {listed}. They are excluded. "
            "Add any the agent reaches through another path."
        )

    for item in inventory.unreadable:
        notes.append(
            f"Could not parse {item}, so any tool it declares is missing here."
        )

    notes.append(
        "Source declares what a tool is called and what it takes. It does not "
        "declare whether the effect can be undone, which argument spends "
        "money, or what a ceiling counts against. Those are below, guessed."
    )
    return notes
