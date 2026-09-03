from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from agentmandate import analyse, loads
from agentmandate._producer import (
    ProducerBoundary,
    ProducerResult,
    ProducerSelection,
    analyse_producers,
    migrate_aws_iam_access_key_boundary,
)
from scripts.evidence_lint import lint_directory

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "producer-accepted-synthetic"
IAM_EVIDENCE = ROOT / "docs" / "evidence" / "aws-iam-access-keys"


def _contents() -> dict[str, bytes]:
    return {
        str(path.relative_to(ROOT)): path.read_bytes()
        for path in (
            FIXTURE / "catalogue.json",
            FIXTURE / "outcomes.json",
            FIXTURE / "adapter.py",
        )
    }


def test_accepted_synthetic_fixture_is_complete_and_clean() -> None:
    boundary_text = (FIXTURE / "boundary.json").read_text()
    boundary = ProducerBoundary.from_json(boundary_text)
    selection = ProducerSelection(**json.loads((FIXTURE / "selection.json").read_text()))
    mandate = loads(
        (FIXTURE / "manifest.json").read_text(),
        source=str((FIXTURE / "manifest.json").relative_to(ROOT)),
    )

    boundary.verify_sources(_contents())
    result = analyse_producers(
        mandate,
        (boundary,),
        _contents(),
        (selection,),
        as_of=date(2026, 9, 3),
    )
    rendered = result.to_result().to_json()

    assert boundary.to_json() == boundary_text
    assert boundary.evidence.as_dict() == {
        "confidence": "exact",
        "review": "accepted",
        "reviewer": "synthetic-fixture-reviewer",
        "expires": "2027-09-03",
    }
    assert [len(item.path) for item in analyse(mandate).breaches] == [3]
    assert result.findings == ()
    assert result.authority.breaches == ()
    assert result.applied[0].capacity_kind == "concurrent"
    assert result.applied[0].maximum == 2
    assert ProducerResult.from_json(rendered) == result.to_result()


def test_synthetic_fixture_pins_every_source_and_does_not_review_iam() -> None:
    assert lint_directory(FIXTURE) == []
    assert "synthetic" in (FIXTURE / "catalogue.json").read_text()
    assert "synthetic" in (FIXTURE / "outcomes.json").read_text()

    iam_contents = {
        str(path.relative_to(ROOT)): path.read_bytes()
        for path in (
            IAM_EVIDENCE / "catalogue.json",
            IAM_EVIDENCE / "capture.json",
            IAM_EVIDENCE / "capture.py",
        )
    }
    iam = migrate_aws_iam_access_key_boundary(iam_contents)
    assert iam.evidence.review == "unreviewed"
    assert iam.evidence.reviewer is None
    assert iam.evidence.expires is None
