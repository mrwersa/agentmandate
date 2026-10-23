"""Exercise installation isolation and failed delivery independently of findings."""

import json
import os
import shlex
import subprocess
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from test_action_gate import ROOT, action_gate, outputs
from test_action_gate import workspace as workspace


@pytest.mark.parametrize("breach", [False, True])
@pytest.mark.parametrize("never", [False, True])
@pytest.mark.parametrize("filename", ["agentmandate-report.json", "agentmandate.sarif"])
def test_report_failure_is_usage_error_without_changing_analysis(
    workspace, monkeypatch, capsys, breach, never, filename,
):
    monkeypatch.setenv(
        "INPUT_MANIFEST", "dispute-resolver-v2.yaml" if breach else "dispute-resolver.yaml",
    )
    monkeypatch.setenv("INPUT_FAIL_ON", "never" if never else "findings")
    # A directory is a portable real replace failure, including when tests run as root.
    (workspace / filename).mkdir()
    assert action_gate.main() == 2
    result = outputs(workspace)
    assert result["verdict"] == ("findings" if breach else "clean")
    assert (int(result["findings"]) > 0) == breach
    assert result["report" if filename.endswith("json") else "sarif-file"] == ""
    assert result["sarif-file" if filename.endswith("json") else "report"]
    assert not list(workspace.glob("agentmandate-output-*"))
    captured = capsys.readouterr()
    assert f"Cannot write {filename}" in captured.err
    assert "Traceback" not in captured.err
    assert f"verdict {result['verdict']}" in captured.out


@pytest.mark.parametrize("failed", ["summary", "output", "both"])
def test_github_delivery_failure_keeps_reports_and_returns_usage_error(
    workspace, monkeypatch, capsys, failed,
):
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver.yaml")
    monkeypatch.setenv("INPUT_FAIL_ON", "never")
    for name in ("summary", "output"):
        if failed in {name, "both"}:
            target = workspace / f"blocked-{name}"
            target.mkdir()
            monkeypatch.setattr(action_gate, f"STEP_{name.upper()}", str(target))
    assert action_gate.main() == 2
    report = json.loads((workspace / "agentmandate-report.json").read_text())
    assert report["verdict"] == "clean" and report["findings"] == 0
    assert (workspace / "agentmandate.sarif").is_file()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    if failed in {"summary", "both"}:
        assert "Cannot write job summary" in captured.err
    if failed in {"output", "both"}:
        assert "Cannot write step output verdict" in captured.err
        assert "Cannot write step output repair-report" in captured.err
    else:
        assert outputs(workspace)["verdict"] == "clean"


@pytest.mark.parametrize("unlink_fails", [False, True])
def test_partial_report_is_not_published(tmp_path, monkeypatch, capsys, unlink_fails):
    target = tmp_path / "report.json"
    target.write_text("previous complete report")
    original = action_gate.NamedTemporaryFile

    @contextmanager
    def failed_write(*args, **kwargs):
        with original(*args, **kwargs) as handle:

            class Writer:
                name = handle.name

                def write(self, text):
                    handle.write(text[:3])
                    raise OSError("synthetic full disk")

            yield Writer()

    monkeypatch.setattr(action_gate, "NamedTemporaryFile", failed_write)
    if unlink_fails:
        def failed_unlink(path):
            raise OSError("synthetic cleanup failure")

        monkeypatch.setattr(Path, "unlink", failed_unlink)
    errors = []
    assert action_gate._publish(target, "new report", errors) == ""
    assert target.read_text() == "previous complete report"
    assert len(errors) == 1 and "full disk" in errors[0]
    assert "Cannot write report.json" in capsys.readouterr().err
    assert bool(list(tmp_path.glob("agentmandate-output-*"))) == unlink_fails


def test_report_creation_failure_is_reported(tmp_path, capsys):
    errors = []
    assert action_gate._publish(tmp_path / "missing/report.json", "{}", errors) == ""
    assert len(errors) == 1
    assert "Cannot write report.json" in capsys.readouterr().err


@pytest.mark.parametrize("filename", ["agentmandate-report.json", "agentmandate.sarif"])
def test_report_symlink_does_not_overwrite_a_manifest(workspace, monkeypatch, filename):
    manifest = workspace / "dispute-resolver.yaml"
    original = manifest.read_bytes()
    (workspace / filename).symlink_to(manifest)
    monkeypatch.setenv("INPUT_MANIFEST", manifest.name)
    assert action_gate.main() == 0
    assert manifest.read_bytes() == original
    assert not (workspace / filename).is_symlink()
    assert outputs(workspace)["report"] and outputs(workspace)["sarif-file"]


def test_install_command_ignores_checkout_pip_and_startup_hooks(tmp_path):
    # A minimal local wheel exercises the real composite install argv without network/builds.
    wheel = tmp_path / "agentmandate_install_probe-0.0.0-py3-none-any.whl"
    info = "agentmandate_install_probe-0.0.0.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in {
            "agentmandate_install_probe/__init__.py": 'INSTALLED = "trusted-wheel"\n',
            f"{info}/METADATA": (
                "Metadata-Version: 2.1\nName: agentmandate-install-probe\n"
                "Version: 0.0.0\nProvides-Extra: yaml\n"
            ),
            f"{info}/WHEEL": (
                "Wheel-Version: 1.0\nGenerator: isolation-test\nRoot-Is-Purelib: true\n"
                "Tag: py3-none-any\n"
            ),
            f"{info}/RECORD": "",
        }.items():
            archive.writestr(name, content)
    environment = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = str(environment / "bin/python")
    checkout = tmp_path / "candidate"
    checkout.mkdir()
    poison = checkout / "pip"
    poison.mkdir()
    marker = tmp_path / "candidate-code-executed"
    malicious = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    (poison / "__init__.py").write_text(malicious)
    (poison / "__main__.py").write_text(malicious + "raise SystemExit(0)\n")
    (checkout / "sitecustomize.py").write_text(malicious)
    action = yaml.safe_load((ROOT / "action.yml").read_text())
    install = next(s for s in action["runs"]["steps"] if s.get("name") == "Install AgentMandate")
    args = shlex.split(install["run"].replace("${{ github.action_path }}", str(wheel)))
    args[0] = python
    env = {**os.environ, "PYTHONPATH": str(checkout), "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    result = subprocess.run(
        [*args, "--no-index", "--no-deps"], cwd=checkout, env=env,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    verified = subprocess.run(
        [python, "-I", "-c", "import agentmandate_install_probe as p; print(p.INSTALLED)"],
        cwd=checkout, env=env, capture_output=True, text=True, check=True,
    )
    assert verified.stdout.strip() == "trusted-wheel"
    assert not marker.exists()
