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

The rule that shapes everything below is that a manifest describes exactly one
agent's authority. Overstating it is not a smaller error than understating it:
``reach`` searches whatever graph it is given, so a manifest holding two
agents' tools yields compound paths that no single run could take, and a gate
that reports breaches nobody can reach gets switched off. Where the source
does not settle which agent is meant, this refuses rather than guesses.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .scan import Proposal, _effect_for, _scope_for, _value_arg_for

# Decorators that declare a callable as an agent tool, matched on the trailing
# name because every framework is imported under a different path.
#
# - `tool`          LangChain, LangGraph, Strands Agents, CrewAI, FastMCP
# - `function_tool` OpenAI Agents SDK
# - `ai_function`   Microsoft Agent Framework
TOOL_DECORATORS = frozenset({"tool", "function_tool", "ai_function"})

# Modules those decorators legitimately come from. A decorator imported from
# somewhere else has the right name and an unknown meaning, so it is still
# read and then reported, rather than being trusted or dropped.
FRAMEWORK_MODULES = (
    "langchain",
    "langchain_core",
    "langgraph",
    "strands",
    "crewai",
    "agents",
    "agent_framework",
    "llama_index",
    "mcp",
    "fastmcp",
    "google.adk",
    "semantic_kernel",
    "pydantic_ai",
    "autogen",
)

# Callees that plausibly construct an agent. A `tools=` keyword on anything
# else is a coincidence until somebody says otherwise, and letting an
# unrelated helper decide the inventory would be silent misattribution.
AGENT_CALLEE_HINTS = (
    "agent",
    "swarm",
    "crew",
    "team",
    "assistant",
    "workflow",
    "graph",
    "orchestrator",
    "supervisor",
    "executor",
    "toolnode",
)

# Keyword arguments through which a framework accepts an explicit tool name.
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


class InventoryError(ValueError):
    """The source does not settle what this agent's authority is."""


@dataclass(frozen=True)
class Declaration:
    """One decorated function, and where it came from."""

    proposal: Proposal
    symbol: str
    module: str
    origin: str | None

    @property
    def name(self) -> str:
        return self.proposal.name

    @property
    def confirmed(self) -> bool:
        """Whether the decorator came from a framework this knows."""
        if self.origin is None:
            return False
        return any(
            self.origin == module or self.origin.startswith(f"{module}.")
            for module in FRAMEWORK_MODULES
        )

    @property
    def qualified(self) -> str:
        return f"{self.module}:{self.symbol}"


@dataclass(frozen=True)
class Reference:
    """One entry in a tool list, as written."""

    symbol: str
    hint: str | None


@dataclass(frozen=True)
class Binding:
    """One place the source hands a list of tools to something."""

    label: str
    where: str
    module: str
    callee: str
    references: tuple[Reference, ...]
    unresolved: tuple[str, ...]
    listed: bool
    recognised: bool

    @property
    def empty(self) -> bool:
        """An explicit list holding nothing. Not the same as no binding."""
        return self.listed and not self.references and not self.unresolved


@dataclass
class Inventory:
    """Everything the source said, and everything it did not say."""

    proposals: list[Proposal] = field(default_factory=list)
    selected: Binding | None = None
    bindings: list[Binding] = field(default_factory=list)
    unbound: list[str] = field(default_factory=list)
    undeclared: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    unconfirmed: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    united: bool = False
    files_read: int = 0

    @property
    def candidates(self) -> list[Binding]:
        """Tool lists passed to something that does not look like an agent."""
        return [
            binding
            for binding in self.bindings
            if not binding.recognised and binding is not self.selected
        ]


def _decorator_name(node: ast.expr) -> tuple[str | None, str | None, ast.Call | None]:
    """Return a decorator's trailing name, the name holding it, and its call.

    ``@mcp.tool()`` is the tool decorator named by ``tool``, but what says
    where it came from is ``mcp``, so both are needed to attribute it.
    """
    call = node if isinstance(node, ast.Call) else None
    target = call.func if call is not None else node
    if isinstance(target, ast.Attribute):
        holder = target.value
        return target.attr, holder.id if isinstance(holder, ast.Name) else None, call
    if isinstance(target, ast.Name):
        return target.id, target.id, call
    return None, None, call


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


def _reference(node: ast.expr) -> Reference | None:
    """Read a tool list entry, keeping the module it was qualified with."""
    if isinstance(node, ast.Name):
        return Reference(symbol=node.id, hint=None)
    if isinstance(node, ast.Attribute):
        holder = node.value
        hint = holder.id if isinstance(holder, ast.Name) else None
        return Reference(symbol=node.attr, hint=hint)
    return None


def _callee_name(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return "<expression>"


def _looks_like_an_agent(callee: str) -> bool:
    lowered = callee.lower().replace("_", "")
    return any(hint in lowered for hint in AGENT_CALLEE_HINTS)


class _Reader(ast.NodeVisitor):
    """Collect tool declarations and tool bindings from one module."""

    def __init__(self, module: str, tree: ast.Module) -> None:
        self.module = module
        self.declarations: list[Declaration] = []
        self.bindings: list[Binding] = []
        # `from strands import tool as strands_tool` is common enough that
        # matching the decorator name alone misses the declaration entirely.
        self.aliases: dict[str, str] = {}
        # Where each imported name came from, so a decorator can be attributed
        # and a bound symbol can be resolved to the right module.
        self.origins: dict[str, str] = {}
        self.labels: dict[int, str] = {}
        self._scan_imports(tree)
        self._scan_labels(tree)

    def _scan_imports(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or "." * node.level
                for alias in node.names:
                    bound = alias.asname or alias.name
                    self.origins[bound] = module
                    if alias.asname:
                        self.aliases[alias.asname] = alias.name.rsplit(".", 1)[-1]
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    self.origins[bound] = alias.name
                    if alias.asname:
                        self.aliases[alias.asname] = alias.name.rsplit(".", 1)[-1]

    def _scan_labels(self, tree: ast.Module) -> None:
        """Name each binding after the variable it is assigned to."""
        for node in ast.walk(tree):
            target: ast.expr | None = None
            value: ast.expr | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign):
                target, value = node.target, node.value
            if isinstance(target, ast.Name) and isinstance(value, ast.Call):
                self.labels[id(value)] = target.id

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            name, holder, call = _decorator_name(decorator)
            if name is None:
                continue
            resolved = self.aliases.get(name, name)
            if resolved not in TOOL_DECORATORS:
                continue
            declared = _declared_name(call, node.name)
            effect, guessed = _effect_for(declared)
            properties = _properties(node)
            self.declarations.append(
                Declaration(
                    proposal=Proposal(
                        name=declared,
                        effect=effect,
                        guessed_effect=guessed,
                        scope=_scope_for(properties),
                        value_arg=_value_arg_for(properties),
                        description=_description(node),
                    ),
                    symbol=node.name,
                    module=self.module,
                    origin=self.origins.get(holder or name),
                )
            )
            break
        self.generic_visit(node)

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Call(self, node: ast.Call) -> None:
        listed: ast.expr | None = None
        found = False
        if isinstance(node.func, ast.Attribute) and node.func.attr == "bind_tools":
            found = True
            listed = node.args[0] if node.args else None
        else:
            for keyword in node.keywords:
                if keyword.arg == "tools":
                    found = True
                    listed = keyword.value
                    break

        # `bind_tools()` with no argument passes nothing at all, which is not
        # the same as passing an empty list. Recording it would turn a
        # degenerate call into a claim that the agent has no tools.
        if found and listed is not None:
            self._record(node, listed)
        self.generic_visit(node)

    def _record(self, call: ast.Call, listed: ast.expr) -> None:
        callee = _callee_name(call)
        where = f"{self.module}:{call.lineno}"
        label = self.labels.get(id(call)) or f"{callee}@{call.lineno}"

        references: list[Reference] = []
        unresolved: list[str] = []
        is_list = isinstance(listed, (ast.List, ast.Tuple, ast.Set))
        if not is_list:
            # `tools=get_tools()` or `tools=TOOLS`. The list exists at runtime
            # and this cannot see into it, which is the honest thing to report.
            unresolved.append(ast.unparse(listed))
        else:
            for element in listed.elts:  # type: ignore[union-attr]
                reference = _reference(element)
                if reference is None:
                    unresolved.append(ast.unparse(element))
                else:
                    references.append(reference)

        self.bindings.append(
            Binding(
                label=label,
                where=where,
                module=self.module,
                callee=callee,
                references=tuple(references),
                unresolved=tuple(unresolved),
                listed=is_list,
                recognised=_looks_like_an_agent(callee)
                or callee == "bind_tools",
            )
        )


def _python_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if not any(part in SKIPPED_DIRECTORIES for part in path.parts)
    ]


def _stem(module: str) -> str:
    return Path(module).stem


def _resolve(
    reference: Reference,
    binding: Binding,
    by_symbol: dict[str, list[Declaration]],
    origins: dict[str, dict[str, str]],
) -> tuple[Declaration | None, str | None]:
    """Find the declaration a bound name refers to, from where it was written.

    Two modules declaring a tool called ``refund`` is ordinary. Picking
    whichever file sorts first would attribute one agent's signature, scope,
    and ceiling to another agent's tool, so the module the reference came
    through decides, and a genuinely ambiguous name is reported.
    """
    matches = by_symbol.get(reference.symbol, [])
    if not matches:
        return None, None

    if reference.hint is not None:
        # `tools.refund` names the module outright.
        scoped = [d for d in matches if _stem(d.module) == _stem(reference.hint)]
        if scoped:
            return scoped[0], None

    imported = origins.get(binding.module, {}).get(reference.symbol)
    if imported is not None:
        stem = _stem(imported.rsplit(".", 1)[-1])
        scoped = [d for d in matches if _stem(d.module) == stem]
        if scoped:
            return scoped[0], None

    local = [d for d in matches if d.module == binding.module]
    if local:
        return local[0], None

    if len(matches) == 1:
        return matches[0], None

    where = ", ".join(sorted(d.qualified for d in matches))
    return None, f"{reference.symbol} ({where})"


def collect(
    root: str | Path,
    *,
    binding: str | None = None,
    union: bool = False,
) -> Inventory:
    """Read tool declarations and bindings from a file or a directory tree.

    ``binding`` selects one tool list by label when the source holds several.
    ``union`` merges them instead, which is only correct when the agents
    genuinely share authority.
    """
    base = Path(root)
    if not base.exists():
        raise InventoryError(f"{base} does not exist")

    paths = _python_files(base)
    if not paths:
        raise InventoryError(f"{base} contains no Python files")

    inventory = Inventory()
    declarations: list[Declaration] = []
    origins: dict[str, dict[str, str]] = {}

    for path in paths:
        module = str(path.relative_to(base) if base.is_dir() else path.name)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            # One unparsable file must not lose the rest of the inventory, and
            # must not pass silently either: a manifest is being built from
            # what was read, and this file was not read.
            inventory.unreadable.append(f"{module}: {exc.__class__.__name__}")
            continue

        inventory.files_read += 1
        reader = _Reader(module, tree)
        reader.visit(tree)
        declarations.extend(reader.declarations)
        inventory.bindings.extend(reader.bindings)
        origins[module] = reader.origins

    by_symbol: dict[str, list[Declaration]] = {}
    for declaration in declarations:
        by_symbol.setdefault(declaration.symbol, []).append(declaration)

    chosen = _choose(inventory.bindings, binding, union)
    if chosen is None:
        # Nothing bound anything. Every declaration is offered, and the note
        # says the list has not been narrowed to one agent.
        selected = declarations
    else:
        inventory.selected = None if union else chosen[0]
        inventory.united = union and len(chosen) > 1
        selected = []
        for site in chosen:
            for reference in site.references:
                declaration, ambiguity = _resolve(
                    reference, site, by_symbol, origins
                )
                if ambiguity is not None:
                    inventory.ambiguous.append(ambiguity)
                elif declaration is None:
                    inventory.undeclared.append(reference.symbol)
                elif declaration not in selected:
                    selected.append(declaration)
            inventory.unresolved.extend(
                f"{site.where}: {entry}" for entry in site.unresolved
            )

        if all(site.empty for site in chosen):
            listed = ", ".join(site.label for site in chosen)
            raise InventoryError(
                f"the tool list at {listed} is empty, so this agent has no "
                f"authority to describe. An empty list is not the same as no "
                f"list, and listing every declared tool here would grant "
                f"authority the source withholds."
            )

    # Qualified where the bare name would be misleading. Two modules declaring
    # `refund` and one of them bound is exactly the case a reader has to see.
    clashing = {
        d.name for d in declarations if sum(o.name == d.name for o in declarations) > 1
    }
    inventory.unbound = sorted(
        d.qualified if d.name in clashing else d.name
        for d in declarations
        if d not in selected
    )
    inventory.unconfirmed = sorted(
        f"{d.name} (from {d.origin or 'an unresolved import'})"
        for d in selected
        if not d.confirmed
    )
    inventory.undeclared = sorted(set(inventory.undeclared))
    inventory.ambiguous = sorted(set(inventory.ambiguous))

    seen: dict[str, Declaration] = {}
    for declaration in selected:
        clash = seen.get(declaration.name)
        if clash is not None:
            inventory.ambiguous.append(
                f"{declaration.name} ({clash.qualified}, {declaration.qualified})"
            )
            continue
        seen[declaration.name] = declaration
        inventory.proposals.append(declaration.proposal)

    return inventory


def _choose(
    bindings: list[Binding], wanted: str | None, union: bool
) -> list[Binding] | None:
    """Decide which tool list describes the agent, or refuse to."""
    if wanted is not None:
        matched = [b for b in bindings if b.label == wanted or b.where == wanted]
        if not matched:
            offered = ", ".join(b.label for b in bindings) or "none"
            raise InventoryError(
                f"no tool binding called {wanted!r}. Found: {offered}"
            )
        return matched

    agentic = [b for b in bindings if b.recognised]
    if not agentic:
        return None
    if len(agentic) == 1:
        return agentic
    if union:
        return agentic

    offered = "\n".join(
        f"  {b.label:24} {b.where}  ({len(b.references)} tool(s))" for b in agentic
    )
    raise InventoryError(
        "the source builds more than one agent, and a manifest describes one "
        "agent's authority. Their union would let `reach` compose a path "
        "across tools that never share a run.\n\n"
        f"{offered}\n\n"
        "Choose one with --binding NAME, or pass --union-bindings if they "
        "genuinely share authority."
    )


def notes_for(inventory: Inventory) -> list[str]:
    """Turn everything the read could not establish into review lines."""
    notes: list[str] = []

    if inventory.selected is not None:
        notes.append(
            f"Inventory taken from the tool list at {inventory.selected.where} "
            f"({inventory.selected.label}). Only tools given to that agent are "
            "below."
        )
    elif inventory.united:
        notes.append(
            "This is the union of every agent in the source, which you asked "
            "for. `reach` will compose paths across tools that may never share "
            "a run, so read its findings with that in mind."
        )
    else:
        notes.append(
            "No agent was found taking a `tools=[...]` list, so this lists "
            "every declared tool in the source. A mandate should describe one "
            "agent's authority. Remove any tool this agent is not given."
        )

    for item in inventory.unresolved:
        notes.append(
            f"A binding passes tools this read cannot enumerate ({item}). Those "
            "tools are missing from the list below, and a later diff would "
            "report them as newly added authority. Add them by hand."
        )

    if inventory.ambiguous:
        listed = "; ".join(inventory.ambiguous)
        notes.append(
            f"More than one declaration answers to the same name: {listed}. "
            "None of them was chosen, because picking one would attribute the "
            "wrong signature, scope, and ceiling to this agent's tool."
        )

    if inventory.undeclared:
        listed = ", ".join(inventory.undeclared)
        notes.append(
            f"Bound to the agent but declared nowhere in the scanned path: "
            f"{listed}. They are missing from the list below. Widen --source, "
            f"or add them by hand."
        )

    for candidate in inventory.candidates:
        notes.append(
            f"{candidate.where} passes `tools=` to {candidate.callee}, which "
            "does not look like an agent, so it was ignored. If it does build "
            f"one, select it with --binding {candidate.label}."
        )

    if inventory.unconfirmed:
        listed = ", ".join(inventory.unconfirmed)
        notes.append(
            f"These carry a tool decorator from somewhere this does not "
            f"recognise as an agent framework: {listed}. They are included, "
            "because a re-exported decorator is common, but check they really "
            "are agent tools."
        )

    if inventory.unbound:
        listed = ", ".join(inventory.unbound)
        notes.append(
            f"Declared but not given to this agent: {listed}. They are "
            "excluded. Add any it reaches through another path."
        )

    for item in inventory.unreadable:
        notes.append(f"Could not parse {item}, so any tool it declares is missing here.")

    notes.append(
        "Source declares what a tool is called and what it takes. It does not "
        "declare whether the effect can be undone, which argument spends "
        "money, or what a ceiling counts against. Those are below, guessed."
    )
    return notes
