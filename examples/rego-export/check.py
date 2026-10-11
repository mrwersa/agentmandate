"""Check an export with the pinned native OPA engine, not a Python evaluator."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def check(directory, opa):
    directory = Path(directory)
    target = json.loads(Path(__file__).with_name("opa-target.json").read_text())
    # This example pins the Linux x86-64 static binary as well as its version.
    assert hashlib.sha256(Path(opa).read_bytes()).hexdigest() == target["sha256"]
    version = subprocess.check_output([str(opa), "version"], text=True)
    assert version.splitlines()[0] == f"Version: {target['version']}"
    receipt = json.loads((directory / "export.json").read_text())
    assert receipt["target"]["engine_version"] == target["version"]
    assert receipt["native_validation"] == "not_run"
    cases = json.loads((directory / "tests.json").read_text())["cases"]
    assert cases and all(row["expected"] in {"allow", "deny"} for row in cases)
    subprocess.run(
        [
            str(opa),
            "check",
            "--strict",
            "--schema",
            str(directory / "schema.json"),
            str(directory / "policy.rego"),
        ],
        check=True,
    )
    checked = json.loads(subprocess.check_output([
        str(opa), "test", "--format=json", str(directory / "policy.rego"),
        str(directory / "policy_test.rego"), str(directory / "tests.json"),
    ], text=True))
    assert len(checked) == 1 and checked[0]["name"] == "test_generated_requests"
    assert checked[0]["package"] == "data." + receipt["mapping"]["package"]
    assert not checked[0].get("fail") and not checked[0].get("skip")
    return {
        "engine": "OPA",
        "engine_version": target["version"],
        "validation": "passed",
        "generated_requests": len(cases),
        "scope": receipt["scope"],
        "losses": receipt["losses"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default=str(Path(__file__).with_name("generated")))
    parser.add_argument("--opa", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.directory, args.opa.resolve()), sort_keys=True))
