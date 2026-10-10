"""The planning score must account for every roadmap initiative exactly once."""

import copy
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "roadmap_progress", ROOT / "scripts/roadmap_progress.py"
)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
LEDGER = json.loads((ROOT / "docs/roadmap-progress.json").read_text())


def test_score_accounts_for_every_roadmap_initiative():
    roadmap = (ROOT / "ROADMAP.md").read_text()
    for phase in LEDGER["phases"]:
        section = roadmap.split(f"## {phase['title']}\n", 1)[1].split("\n## ", 1)[0]
        titles = re.findall(r"^\| \*\*(.*?)\*\*", section, re.MULTILINE)
        assert titles == [row["title"] for row in phase["initiatives"]]
    result = module.calculate(LEDGER)
    assert [p["initiatives"] for p in result["phases"]] == [4, 6, 5, 5, 4]
    assert [p["percent"] for p in result["phases"]] == [100, 58.33, 30, 0, 0]
    assert result["overall"] == {"points": 9.0, "initiatives": 24, "percent": 37.5}
    assert result["first_three_phases"]["percent"] == 60
    assert "37.5%" in roadmap and "58.33%" in roadmap


@pytest.mark.parametrize("change", ["status", "reason", "evidence", "phase", "title", "empty"])
def test_malformed_ledger_cannot_produce_a_score(change):
    value = copy.deepcopy(LEDGER)
    row = value["phases"][0]["initiatives"][0]
    if change == "status":
        row["status"] = "almost_done"
    elif change == "reason":
        row["reason"] = " "
    elif change == "evidence":
        row["evidence"] = "../missing.md"
    elif change == "phase":
        value["phases"].append(value["phases"][0])
    elif change == "title":
        value["phases"][0]["initiatives"].append(row)
    else:
        value["phases"] = []
    with pytest.raises(ValueError):
        module.calculate(value)


def test_calculation_cli_prints_the_same_total(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["roadmap_progress"])
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["overall"]["percent"] == 37.5


@pytest.mark.parametrize("content", [None, "{", '{"phases": []}'])
def test_calculation_cli_refuses_missing_or_malformed_ledgers(tmp_path, monkeypatch, content):
    path = tmp_path / "ledger.json"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr("sys.argv", ["roadmap_progress", "--ledger", str(path)])
    with pytest.raises(SystemExit) as failure:
        module.main()
    assert failure.value.code == 2
