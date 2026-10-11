"""Shared strict mapping primitives and explicit losses for stateless exporters."""


def object_fields(value, fields, where):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f"{where} must contain exactly {', '.join(sorted(fields))}")
    return value


def string(value):
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(c) < 32 or ord(c) > 126 for c in value)
    ):
        raise ValueError("export mapping strings must be non-empty printable ASCII")
    return value


def pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError(f"duplicate export mapping key: {key}")
        result[key] = value
    return result


def unused(ids):
    name = "__agentmandate_unmapped__"
    while name in ids:
        name += "_"
    return name


def stateful_losses(mandate, target):
    losses = []

    def loss(code, subject, detail):
        losses.append({"code": code, "subject": subject, "detail": detail})

    if mandate.limits.total is not None:
        loss(
            "limits.total",
            mandate.agent,
            f"{target} requests do not retain cumulative monetary spend.",
        )
    for effect in sorted(mandate.limits.effects):
        loss("limits.effects", effect, f"{target} requests do not retain effect-call counts.")
    if mandate.roles:
        loss("roles", mandate.agent, "Role views and maker-checker analysis are not compiled.")
    for tool in sorted(mandate.tools, key=lambda t: t.name):
        if tool.requires:
            loss(
                "tool.requires",
                tool.name,
                "Produced-binding prerequisites require execution history.",
            )
        if tool.produces is not None:
            loss(
                "tool.produces",
                tool.name,
                "Binding production and cardinality require execution history.",
            )
        if tool.spends_value:
            loss(
                "tool.ceiling",
                tool.name,
                "A tool ceiling is cumulative per binding; "
                "a per-call amount check is not equivalent.",
            )
    return losses
