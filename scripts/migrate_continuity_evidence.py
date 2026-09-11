"""Regenerate canonical continuity artifacts from committed provider evidence.

This repository tool owns evidence-specific conversion. The installed runtime
owns strict artifact readers, IR projection, and reconciliation only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agentmandate._continuity import (
    AgentCoreContinuity,
    AgentCoreControl,
    AnthropicContinuity,
    AnthropicControl,
    ContinuityBinding,
    ContinuityEvidence,
    ContinuityFormatError,
    ContinuitySource,
    _date,
    _digest,
    _load,
    _record,
    _string,
    _utc,
)


def _captured(contents: dict[str, bytes], locator: str) -> dict[str, Any]:
    try:
        content = contents[locator]
    except KeyError as exc:
        raise ContinuityFormatError(
            f"continuity migration is missing source locator {locator}"
        ) from exc
    if not isinstance(content, bytes):
        raise ContinuityFormatError("continuity migration source contents must be bytes")
    value = _load(content.decode("utf-8"), f"continuity source {locator}")
    if not isinstance(value, dict):
        raise ContinuityFormatError(f"continuity source {locator} must contain an object")
    return value


def _migration_sources(
    contents: dict[str, bytes], kinds: dict[str, str], expected_digests: dict[str, str]
) -> tuple[ContinuitySource, ...]:
    if set(contents) != set(kinds) or set(kinds) != set(expected_digests):
        difference = sorted(set(contents) ^ set(kinds) | (set(kinds) ^ set(expected_digests)))
        locator = difference[0] if difference else "<unknown>"
        raise ContinuityFormatError(f"continuity migration source set differs at locator {locator}")
    result = []
    for index, locator in enumerate(sorted(contents)):
        actual = hashlib.sha256(contents[locator]).hexdigest()
        if actual != expected_digests[locator]:
            raise ContinuityFormatError(
                f"continuity migration source bytes do not match reviewed locator {locator}"
            )
        result.append(
            ContinuitySource(
                id=f"source:{index + 1}",
                kind=kinds[locator],
                locator=locator,
                content_sha256=actual,
            )
        )
    return tuple(result)


def _migration_evidence() -> ContinuityEvidence:
    # Migration proves byte identity, not an independently accountable review.
    return ContinuityEvidence("exact", "unreviewed", None, None)


def migrate_agentcore_binding(contents: dict[str, bytes]) -> ContinuityBinding:
    """Migrate the reviewed AgentCore signed-binding capture without verifying Ed25519."""

    locators = {
        "docs/evidence/agentcore-refund-policy/mandate-binding.json": "signed-binding",
        "docs/evidence/agentcore-refund-policy/mandate-binding-result.json": "binding-evaluation",
        "docs/evidence/agentcore-refund-policy/binding-public-key.pem": "verification-key",
    }
    sources = _migration_sources(
        contents,
        locators,
        {
            "docs/evidence/agentcore-refund-policy/mandate-binding.json": (
                "d68090083664b72203acd6fe9faa33fdae86499d2b201c3c8927e5754f403ace"
            ),
            "docs/evidence/agentcore-refund-policy/mandate-binding-result.json": (
                "aa80fa7ce4a5543c95adad05e0e6e68a5200b1d89073a96074f440584e3bf74e"
            ),
            "docs/evidence/agentcore-refund-policy/binding-public-key.pem": (
                "c5dff1d6d4eb4212c9ff42ed15e8b7a0f8fa1f109d5df9488299b641ecf38536"
            ),
        },
    )
    binding = _captured(contents, "docs/evidence/agentcore-refund-policy/mandate-binding.json")
    result = _captured(
        contents, "docs/evidence/agentcore-refund-policy/mandate-binding-result.json"
    )
    expected_binding = {
        "binding_version",
        "expires_at",
        "issued_at",
        "issuer",
        "mandate_sha256",
        "policy_sha256",
        "principal",
        "signature",
    }
    _record(binding, "migration.binding", expected_binding)
    if binding["binding_version"] != 1:
        raise ContinuityFormatError("continuity migration requires AgentCore binding version 1")
    controls = result.get("local_controls")
    same = result.get("same_signed_mandate")
    different = result.get("different_signed_mandate")
    if (
        result.get("mandate_binding_evaluation_version") != 1
        or not isinstance(controls, list)
        or not isinstance(same, dict)
        or not isinstance(different, dict)
        or [call.get("outcome") for call in same.get("calls", [])] != ["allow", "deny"]
        or [call.get("outcome") for call in different.get("calls", [])] != ["allow"]
        or {control.get("result") for control in controls} != {"rejected-before-network"}
    ):
        raise ContinuityFormatError("continuity migration binding controls do not match evidence")
    migrated = ContinuityBinding(
        1,
        "agentmandate.continuity-binding",
        1,
        "bindings/agentcore-refund",
        _digest(binding["mandate_sha256"], "migration.binding.mandate_sha256"),
        _string(binding["principal"], "migration.binding.principal"),
        "aws-agentcore",
        "policy_session",
        "agentcore-refund-gateway",
        _digest(binding["policy_sha256"], "migration.binding.policy_sha256"),
        _utc(binding["issued_at"], "migration.binding.issued_at"),
        _utc(binding["expires_at"], "migration.binding.expires_at"),
        "sha256_uuid_v1",
        "reviewed-policy-session",
        "ed25519",
        "exclusive_adapter",
        sources,
        _migration_evidence(),
    )
    return ContinuityBinding.from_json(migrated.to_json())


def migrate_agentcore_continuity(contents: dict[str, bytes]) -> AgentCoreContinuity:
    """Migrate reviewed AgentCore repetition summaries into the provider profile."""

    base = "docs/evidence/agentcore-refund-policy/"
    names = {
        "temporal-repetition.json": "temporal-decisions",
        "temporal-transition-confirmation-summary.json": "revision-control",
        "temporal-update-repetition.json": "revision-decisions",
        "binding-repetition.json": "binding-decisions",
        "binding-policy-revision-repetition.json": "binding-revision-decisions",
    }
    locators = {base + name: kind for name, kind in names.items()}
    sources = _migration_sources(
        contents,
        locators,
        {
            base + "temporal-repetition.json": (
                "2bb58ba1a567da8f2ac020585f56c2ac6a60a378e52cf29be8a221255f35cc57"
            ),
            base + "temporal-transition-confirmation-summary.json": (
                "129c018ea16266e51187cf9d499fa989ed93cb3d33da8b8a591891dedf17d512"
            ),
            base + "temporal-update-repetition.json": (
                "c130c0c5aaf812dcc1a39d8e6b930cbf4bee667745876b0ab36911c5351bd7a5"
            ),
            base + "binding-repetition.json": (
                "d1ca57b3917a9a547e9bd47e47984c56ed9d5041757d932fa180f4776e46b5db"
            ),
            base + "binding-policy-revision-repetition.json": (
                "79bd9022cffee259c7e5e2a52ceccb924fb804d214690962ae534061a85776f9"
            ),
        },
    )
    source_by_locator = {source.locator: source.id for source in sources}
    temporal = _captured(contents, base + "temporal-repetition.json")
    semantic = _captured(contents, base + "temporal-transition-confirmation-summary.json")
    update = _captured(contents, base + "temporal-update-repetition.json")
    binding = _captured(contents, base + "binding-repetition.json")
    binding_revision = _captured(contents, base + "binding-policy-revision-repetition.json")
    checks = {
        "temporal": temporal.get("results")
        == {
            "concurrent_exactly_one_allow": 10,
            "concurrent_intervals_overlapped": 10,
            "fresh_sessions_allow_then_allow": 10,
            "same_session_allow_then_deny": 10,
        },
        "semantic": semantic.get("results")
        == {
            "alpha_equivalent_revision_changed": 10,
            "byte_identical_revision_unchanged": 10,
            "byte_identical_second_request_denied": 10,
            "description_only_revision_changed": True,
            "description_only_statement_changed": False,
            "fresh_successor_allow_then_deny": 21,
            "maximum_transition_seconds": 15.377992,
            "predecessor_session_rejected_as_stale": 21,
            "whitespace_only_revision_changed": 10,
        },
        "update": update.get("results", {}).get("old_session_rejected_as_stale") == 10,
        "binding": binding.get("results", {}).get("same_binding_allow_then_deny") == 10,
        "binding_revision": binding_revision.get("results", {}).get(
            "same_mandate_across_revision_aggregate"
        )
        == 1200,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ContinuityFormatError(
            f"continuity migration AgentCore control does not match source {failed[0]}"
        )
    ref = lambda name: (source_by_locator[base + name],)  # noqa: E731
    controls = (
        AgentCoreControl(
            "same-session",
            "same_boundary",
            10,
            600,
            (1000,),
            ("allow", "deny"),
            None,
            None,
            False,
            None,
            "unestablished",
            ref("temporal-repetition.json"),
        ),
        AgentCoreControl(
            "fresh-sessions",
            "fresh_session",
            10,
            600,
            (1000,),
            ("allow", "allow"),
            None,
            None,
            True,
            None,
            "unestablished",
            ref("temporal-repetition.json"),
        ),
        AgentCoreControl(
            "concurrent-session",
            "concurrent_dispatch",
            10,
            600,
            (1000,),
            ("allow", "deny"),
            None,
            None,
            False,
            True,
            "unestablished",
            ref("temporal-repetition.json"),
        ),
        AgentCoreControl(
            "byte-identical-write",
            "configuration_revision",
            10,
            600,
            (1000,),
            ("allow", "deny"),
            True,
            False,
            False,
            None,
            "unestablished",
            ref("temporal-transition-confirmation-summary.json"),
        ),
        AgentCoreControl(
            "equivalent-revision",
            "configuration_revision",
            10,
            600,
            (1000,),
            ("allow", "stale_session", "allow", "deny"),
            True,
            True,
            True,
            None,
            "unestablished",
            ref("temporal-transition-confirmation-summary.json"),
        ),
        AgentCoreControl(
            "whitespace-revision",
            "configuration_revision",
            10,
            600,
            (1000,),
            ("allow", "stale_session", "allow", "deny"),
            True,
            True,
            True,
            None,
            "unestablished",
            ref("temporal-transition-confirmation-summary.json"),
        ),
        AgentCoreControl(
            "description-revision",
            "configuration_revision",
            1,
            600,
            (1000,),
            ("allow", "stale_session", "allow", "deny"),
            True,
            True,
            True,
            None,
            "unestablished",
            ref("temporal-transition-confirmation-summary.json"),
        ),
        AgentCoreControl(
            "limit-revision",
            "limit_revision",
            10,
            600,
            (1000, 1001),
            ("allow", "stale_session", "allow"),
            None,
            True,
            True,
            None,
            "unestablished",
            ref("temporal-update-repetition.json"),
        ),
        AgentCoreControl(
            "signed-binding",
            "same_boundary",
            10,
            600,
            (1000,),
            ("allow", "deny", "rejected_before_network"),
            True,
            None,
            False,
            None,
            "exclusive_adapter",
            ref("binding-repetition.json"),
        ),
        AgentCoreControl(
            "binding-revision",
            "configuration_revision",
            10,
            600,
            (1000, 1001),
            ("allow", "stale_session", "allow"),
            True,
            True,
            True,
            None,
            "exclusive_adapter",
            ref("binding-policy-revision-repetition.json"),
        ),
    )
    migrated = AgentCoreContinuity(
        1,
        "agentmandate.agentcore-continuity",
        1,
        "aws-agentcore",
        "agentcore-refund-gateway",
        "MCP 2025-03-26",
        tuple(sorted(controls, key=lambda control: control.id)),
        sources,
        _migration_evidence(),
    )
    return AgentCoreContinuity.from_json(migrated.to_json())


def migrate_anthropic_continuity(contents: dict[str, bytes]) -> AnthropicContinuity:
    """Migrate reviewed managed-budget summaries without inventing a native binding."""

    base = "docs/evidence/anthropic-managed-budget/"
    names = {
        "protocol.json": "single-agent-protocol",
        "confirmation.json": "single-agent-decisions",
        "multiagent-protocol.json": "multiagent-protocol",
        "multiagent-confirmation.json": "multiagent-decisions",
    }
    locators = {base + name: kind for name, kind in names.items()}
    sources = _migration_sources(
        contents,
        locators,
        {
            base + "protocol.json": (
                "5e7ad330270b36adce17c7b4e9f374ca2f03b548e1c251ab1b37eabb0a6a4001"
            ),
            base + "confirmation.json": (
                "f2b70d732f94ee3381b377fdac58ccb6150922dd5f96a057a9ee66505cfabe51"
            ),
            base + "multiagent-protocol.json": (
                "b56802cd8a4be4ace4369750114c9808d2589e04b34e20527c69c1965819f16e"
            ),
            base + "multiagent-confirmation.json": (
                "7300038f4aeb13fc1b9b35c6a06b6eee9a86d0907bdc3a6af46fd8cc8b2819f7"
            ),
        },
    )
    source_by_locator = {source.locator: source.id for source in sources}
    protocol = _captured(contents, base + "protocol.json")
    confirmation = _captured(contents, base + "confirmation.json")
    multi_protocol = _captured(contents, base + "multiagent-protocol.json")
    multi = _captured(contents, base + "multiagent-confirmation.json")
    if (
        protocol.get("protocol_version") != 1
        or confirmation.get("evidence_version") != 1
        or multi_protocol.get("protocol_version") != 1
        or multi.get("evidence_version") != 1
        or confirmation.get("protocol_sha256")
        != hashlib.sha256(contents[base + "protocol.json"]).hexdigest()
        or multi.get("protocol_sha256")
        != hashlib.sha256(contents[base + "multiagent-protocol.json"]).hexdigest()
    ):
        raise ContinuityFormatError("continuity migration Anthropic protocol join failed")
    single_trials = confirmation.get("trials")
    multi_trials = multi.get("trials")
    if not isinstance(single_trials, list) or not isinstance(multi_trials, list):
        raise ContinuityFormatError("continuity migration Anthropic trials must be arrays")
    if len(single_trials) != 30 or len(multi_trials) != 30:
        raise ContinuityFormatError("continuity migration Anthropic trial counts differ")

    def single_costs(cell: str) -> tuple[int, ...]:
        selected = [trial for trial in single_trials if trial.get("cell") == cell]
        if len(selected) != 10:
            raise ContinuityFormatError(f"continuity migration Anthropic cell {cell} differs")
        costs = []
        for trial in selected:
            if cell == "cap_revision_control":
                costs.append(trial["revision"]["cost_immediately_after"])
            elif cell == "fresh_session_replication":
                costs.append(
                    max(
                        unit["list_cost_minor_units"] for unit in trial["sessions"][1]["work_units"]
                    )
                )
            else:
                costs.append(max(unit["list_cost_minor_units"] for unit in trial["work_units"]))
        return tuple(costs)

    def single_before_costs(cell: str) -> tuple[int, ...]:
        selected = [trial for trial in single_trials if trial.get("cell") == cell]
        if cell == "fresh_session_replication":
            return tuple(
                max(unit["list_cost_minor_units"] for unit in trial["sessions"][0]["work_units"])
                for trial in selected
            )
        return tuple(trial["revision"]["consumed_before"] for trial in selected)

    def multi_costs(cell: str) -> tuple[int, ...]:
        selected = [trial for trial in multi_trials if trial.get("cell") == cell]
        if len(selected) != 10 or any(
            not trial.get("topology", {}).get("protocol_conformant") for trial in selected
        ):
            raise ContinuityFormatError(f"continuity migration Anthropic cell {cell} differs")
        return tuple(trial["list_cost_minor_units"] for trial in selected)

    single_sources = (
        source_by_locator[base + "protocol.json"],
        source_by_locator[base + "confirmation.json"],
    )
    multi_sources = (
        source_by_locator[base + "multiagent-protocol.json"],
        source_by_locator[base + "multiagent-confirmation.json"],
    )
    controls = (
        AnthropicControl(
            "sequential",
            "same_boundary",
            10,
            1,
            1,
            None,
            None,
            single_costs("sequential_control"),
            ("budget_reached",),
            None,
            False,
            single_sources,
        ),
        AnthropicControl(
            "fresh-sessions",
            "fresh_session",
            10,
            1,
            1,
            None,
            single_before_costs("fresh_session_replication"),
            single_costs("fresh_session_replication"),
            ("budget_reached",),
            None,
            True,
            single_sources,
        ),
        AnthropicControl(
            "cap-increase",
            "limit_revision",
            10,
            1,
            2,
            None,
            single_before_costs("cap_revision_control"),
            single_costs("cap_revision_control"),
            ("budget_reached",),
            None,
            False,
            single_sources,
        ),
        AnthropicControl(
            "one-child",
            "delegation_handoff",
            10,
            1,
            1,
            1,
            None,
            multi_costs("subagent_handoff"),
            ("budget_reached",),
            True,
            False,
            multi_sources,
        ),
        AnthropicControl(
            "two-children",
            "concurrent_dispatch",
            10,
            1,
            1,
            2,
            None,
            multi_costs("concurrent_subagents_2"),
            ("budget_reached",),
            True,
            False,
            multi_sources,
        ),
        AnthropicControl(
            "four-children",
            "concurrent_dispatch",
            10,
            1,
            1,
            4,
            None,
            multi_costs("concurrent_subagents_4"),
            ("budget_reached",),
            True,
            False,
            multi_sources,
        ),
    )
    migrated = AnthropicContinuity(
        1,
        "agentmandate.anthropic-continuity",
        1,
        _string(protocol.get("provider"), "migration.anthropic.provider"),
        _string(protocol.get("service"), "migration.anthropic.service"),
        _string(protocol.get("beta"), "migration.anthropic.beta"),
        _string(protocol.get("sdk"), "migration.anthropic.sdk"),
        _string(protocol.get("model"), "migration.anthropic.model"),
        _date(protocol.get("capture_date"), "migration.anthropic.capture_date"),
        _digest(protocol.get("binding", {}).get("sha256"), "migration.anthropic.binding"),
        tuple(sorted(controls, key=lambda control: control.id)),
        sources,
        _migration_evidence(),
    )
    return AnthropicContinuity.from_json(migrated.to_json())


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def _contents(locators: tuple[str, ...]) -> dict[str, bytes]:
    return {locator: (ROOT / locator).read_bytes() for locator in locators}


def _migration_cases() -> tuple[
    tuple[Callable[[dict[str, bytes]], Any], tuple[str, ...], str], ...
]:
    agentcore = "docs/evidence/agentcore-refund-policy/"
    anthropic = "docs/evidence/anthropic-managed-budget/"
    return (
        (
            migrate_agentcore_binding,
            (
                agentcore + "mandate-binding.json",
                agentcore + "mandate-binding-result.json",
                agentcore + "binding-public-key.pem",
            ),
            "continuity-binding-v1.json",
        ),
        (
            migrate_agentcore_continuity,
            (
                agentcore + "temporal-repetition.json",
                agentcore + "temporal-transition-confirmation-summary.json",
                agentcore + "temporal-update-repetition.json",
                agentcore + "binding-repetition.json",
                agentcore + "binding-policy-revision-repetition.json",
            ),
            "agentcore-continuity-v1.json",
        ),
        (
            migrate_anthropic_continuity,
            (
                anthropic + "protocol.json",
                anthropic + "confirmation.json",
                anthropic + "multiagent-protocol.json",
                anthropic + "multiagent-confirmation.json",
            ),
            "anthropic-continuity-v1.json",
        ),
    )


def verify_fixtures() -> None:
    for migrate, locators, fixture in _migration_cases():
        contents = _contents(locators)
        migrated = migrate(contents)
        expected = (FIXTURES / fixture).read_text(encoding="utf-8")
        if migrated.to_json() != expected:
            raise ContinuityFormatError(
                f"continuity migration no longer reproduces canonical fixture {fixture}"
            )
        migrated.verify_sources(contents)


def main() -> None:
    verify_fixtures()
    print("continuity evidence migrations: canonical fixtures match source evidence")


if __name__ == "__main__":
    main()
