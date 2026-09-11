"""Private-first live capture for the preregistered AgentCore continuation matrix.

Never commit the raw output produced by this program: it contains live account,
resource, policy, request, and session identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import botocore.auth
import botocore.awsrequest
import botocore.exceptions

HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = HERE / "continuation-protocol.json"
REGION = "us-east-1"
PARTITION = "aws"
LAMBDA_BASIC_POLICY = f"arn:{PARTITION}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
TARGET = "ContinuationTarget"
TOOL = f"{TARGET}___process_refund"
TOOL_DESCRIPTION = "Return a synthetic refund amount without a side effect"
FAIL = "FAIL_ON_ANY_FINDINGS"
IGNORE = "IGNORE_ALL_FINDINGS"
STABLE_ACTIVE_POLLS = 5
CONTROL_TIMEOUT_SECONDS = 600
ABSENT = {"ResourceNotFoundException", "NoSuchEntity", "ResourceNotFound", "NotFoundException"}
LAMBDA_CODE = (
    "def handler(event, context):\n"
    "    del context\n"
    "    arguments = event.get('arguments', event)\n"
    "    return {'processed': True, 'amount': arguments.get('amount')}\n"
)


class StopCampaign(RuntimeError):
    """A preregistered stop rule was met."""


def _now() -> dict[str, Any]:
    utc = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    return {"utc": utc.replace("+00:00", "Z"), "monotonic_ns": time.monotonic_ns()}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, bytes):
        return {"bytes": len(value)}
    return value


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _code(exc: Exception) -> str | None:
    if isinstance(exc, botocore.exceptions.ClientError):
        return exc.response.get("Error", {}).get("Code")
    return None


def _error(exc: Exception) -> dict[str, Any]:
    return {"type": type(exc).__name__, "code": _code(exc), "message": str(exc)[:500]}


def _wait(fetch: Any, ready: set[str], failed: set[str], label: str) -> dict[str, Any]:
    deadline = time.monotonic() + CONTROL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        value = fetch()
        status = value.get("status") or value.get("State")
        if status in ready:
            return value
        if status in failed:
            raise RuntimeError(f"{label} entered {status}: {value.get('statusReasons')}")
        time.sleep(2)
    raise RuntimeError(f"{label} did not become ready before the control-plane timeout")


def _wait_absent(fetch: Any, label: str) -> bool:
    deadline = time.monotonic() + CONTROL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            fetch()
        except botocore.exceptions.ClientError as exc:
            if _code(exc) in ABSENT:
                return True
            raise
        time.sleep(3)
    raise RuntimeError(f"{label} still resolves after deletion")


def _retry(call: Any, retryable: set[str], attempts: int = 20, delay: float = 3.0) -> Any:
    for attempt in range(attempts):
        try:
            return call()
        except botocore.exceptions.ClientError as exc:
            if _code(exc) not in retryable or attempt == attempts - 1:
                raise
            time.sleep(delay)
    raise RuntimeError("retry loop exited without a result")


class Live:
    def __init__(self, output: Path, protocol: dict[str, Any]) -> None:
        self.output = output
        self.protocol = protocol
        self.session = boto3.session.Session(region_name=REGION)
        self.iam = self.session.client("iam")
        self.lam = self.session.client("lambda")
        self.logs = self.session.client("logs")
        self.ctl = self.session.client("bedrock-agentcore-control")
        self.account = self.session.client("sts").get_caller_identity()["Account"]
        self.arn_prefix = f"arn:{PARTITION}:bedrock-agentcore:{REGION}:{self.account}"
        self.state: dict[str, Any] = {"nonce": secrets.token_hex(4), "created": {}}
        self.form: dict[str, Any] = {}

    def _save(self) -> None:
        _write(self.output / "resources.json", self.state)

    def _statement(self, name: str) -> str:
        text = (HERE / name).read_text(encoding="utf-8").rstrip("\n")
        return text.replace(self.protocol["gateway_placeholder"], self.state["gateway_arn"])

    @staticmethod
    def _whitespace(text: str) -> str:
        marker = "when temporal {\n"
        if marker not in text:
            raise RuntimeError("whitespace rule marker is absent from the statement")
        return text.replace(marker, marker + "\n", 1)

    def deploy(self) -> None:
        if self.ctl.list_gateways().get("items") or self.ctl.list_policy_engines().get(
            "policyEngines"
        ):
            raise StopCampaign("another AgentCore Gateway or policy engine exists in the account")
        nonce, created = self.state["nonce"], self.state["created"]
        lambda_trust = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
        lambda_role = f"AgentMandateContinuationLambda{nonce}"
        role = self.iam.create_role(
            RoleName=lambda_role, AssumeRolePolicyDocument=json.dumps(lambda_trust)
        )["Role"]
        created["lambda_role"] = lambda_role
        self._save()
        self.iam.attach_role_policy(
            RoleName=lambda_role,
            PolicyArn=LAMBDA_BASIC_POLICY,
        )
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("lambda_function.py", LAMBDA_CODE)
        function_name = f"agentmandate-continuation-{nonce}"
        function = _retry(
            lambda: self.lam.create_function(
                FunctionName=function_name,
                Runtime="python3.12",
                Role=role["Arn"],
                Handler="lambda_function.handler",
                Code={"ZipFile": archive.getvalue()},
                Timeout=10,
            ),
            {"InvalidParameterValueException"},
        )
        created["lambda_function"] = function_name
        self._save()
        _wait(
            lambda: self.lam.get_function_configuration(FunctionName=function_name),
            {"Active"},
            {"Failed"},
            "Lambda",
        )
        engine = self.ctl.create_policy_engine(name=f"ContinuationPolicyEngine{nonce}")
        created["policy_engine"] = engine["policyEngineId"]
        self._save()
        engine = _wait(
            lambda: self.ctl.get_policy_engine(policyEngineId=created["policy_engine"]),
            {"ACTIVE"},
            {"CREATE_FAILED"},
            "policy engine",
        )
        gateway_trust = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {"aws:SourceAccount": self.account},
                        "ArnLike": {"aws:SourceArn": f"{self.arn_prefix}:*"},
                    },
                }
            ],
        }
        gateway_role = f"AgentMandateContinuationGateway{nonce}"
        gateway_role_arn = self.iam.create_role(
            RoleName=gateway_role, AssumeRolePolicyDocument=json.dumps(gateway_trust)
        )["Role"]["Arn"]
        created["gateway_role"] = gateway_role
        self._save()
        self._gateway_policy(engine["policyEngineArn"], function["FunctionArn"], "*")
        gateway = _retry(
            lambda: self.ctl.create_gateway(
                name=f"continuation-gateway-{nonce}",
                roleArn=gateway_role_arn,
                protocolType="MCP",
                protocolConfiguration={
                    "mcp": {"supportedVersions": ["2025-03-26"], "searchType": "SEMANTIC"}
                },
                authorizerType="AWS_IAM",
                policyEngineConfiguration={"arn": engine["policyEngineArn"], "mode": "ENFORCE"},
                exceptionLevel="DEBUG",
            ),
            {"ValidationException", "AccessDeniedException"},
            attempts=10,
            delay=6.0,
        )
        created["gateway"] = gateway["gatewayId"]
        self._save()
        gateway = _wait(
            lambda: self.ctl.get_gateway(gatewayIdentifier=created["gateway"]),
            {"READY"},
            {"FAILED"},
            "Gateway",
        )
        self.state.update(
            {"gateway_arn": gateway["gatewayArn"], "gateway_url": gateway["gatewayUrl"]}
        )
        self._gateway_policy(engine["policyEngineArn"], function["FunctionArn"], created["gateway"])
        target = self.ctl.create_gateway_target(
            gatewayIdentifier=created["gateway"],
            name=TARGET,
            targetConfiguration={
                "mcp": {
                    "lambda": {
                        "lambdaArn": function["FunctionArn"],
                        "toolSchema": {
                            "inlinePayload": [
                                {
                                    "name": "process_refund",
                                    "description": TOOL_DESCRIPTION,
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"amount": {"type": "integer"}},
                                        "required": ["amount"],
                                    },
                                }
                            ]
                        },
                    }
                }
            },
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        )
        created["target"] = target["targetId"]
        self._save()
        _wait(
            lambda: self.ctl.get_gateway_target(
                gatewayIdentifier=created["gateway"], targetId=created["target"]
            ),
            {"READY"},
            {"FAILED"},
            "Gateway target",
        )
        self.state["deployment"] = {
            "gateway": {
                "authorizer": gateway["authorizerType"],
                "policy_engine_mode": gateway["policyEngineConfiguration"]["mode"],
                "protocol": gateway["protocolType"],
                "status": gateway["status"],
            },
            "boto3": boto3.__version__,
        }
        self._save()

    def _gateway_policy(self, engine_arn: str, function_arn: str, gateway_id: str) -> None:
        prefix = f"arn:{PARTITION}:bedrock-agentcore:{REGION}:{self.account}"
        document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PolicyEngineConfiguration",
                    "Effect": "Allow",
                    "Action": ["bedrock-agentcore:GetPolicyEngine"],
                    "Resource": [engine_arn],
                },
                {
                    "Sid": "PolicyEngineAuthorization",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock-agentcore:AuthorizeAction",
                        "bedrock-agentcore:PartiallyAuthorizeActions",
                    ],
                    "Resource": [engine_arn, f"{prefix}:gateway/{gateway_id}"],
                },
                {
                    "Sid": "PolicySessionWorkloadIdentity",
                    "Effect": "Allow",
                    "Action": ["bedrock-agentcore:GetWorkloadAccessToken"],
                    "Resource": [
                        f"{prefix}:workload-identity-directory/default",
                        f"{prefix}:workload-identity-directory/default/workload-identity/{gateway_id}*",
                    ],
                },
                {
                    "Sid": "InvokeTarget",
                    "Effect": "Allow",
                    "Action": ["lambda:InvokeFunction"],
                    "Resource": [function_arn],
                },
            ],
        }
        self.iam.put_role_policy(
            RoleName=self.state["created"]["gateway_role"],
            PolicyName="ContinuationGatewayExecution",
            PolicyDocument=json.dumps(document),
        )
        time.sleep(10)

    def _create_policy(self, name: str, statement: str, description: str, mode: str) -> str:
        response = self.ctl.create_policy(
            policyEngineId=self.state["created"]["policy_engine"],
            name=name,
            definition={"policy": {"statement": statement}},
            description=description,
            validationMode=mode,
            enforcementMode="ACTIVE",
        )
        policy_id = response["policyId"]
        self.state["created"].setdefault("policies", []).append(policy_id)
        self._save()
        _wait(
            lambda: self.ctl.get_policy(
                policyEngineId=self.state["created"]["policy_engine"], policyId=policy_id
            ),
            {"ACTIVE"},
            {"CREATE_FAILED", "UPDATE_FAILED"},
            name,
        )
        return policy_id

    def _delete_policy(self, policy_id: str) -> None:
        engine = self.state["created"]["policy_engine"]
        self.ctl.delete_policy(policyEngineId=engine, policyId=policy_id)
        _wait_absent(
            lambda: self.ctl.get_policy(policyEngineId=engine, policyId=policy_id), "policy"
        )
        self.state["created"]["policies"].remove(policy_id)
        self._save()

    def policy_snapshot(self) -> dict[str, Any]:
        value = self.ctl.get_policy(
            policyEngineId=self.state["created"]["policy_engine"], policyId=self.form["budget_id"]
        )
        definition = value.get("definition", {})
        statement = (definition.get("policy") or definition.get("cedar") or {}).get("statement", "")
        return {
            "observed": _now(),
            "status": value["status"],
            "status_reasons": value.get("statusReasons", []),
            "updated_at": value["updatedAt"].isoformat(),
            "description": value.get("description"),
            "statement_sha256": _digest(statement),
            "enforcement_mode": value.get("enforcementMode"),
        }

    def update(
        self, statement: str | None = None, description: str | None = None
    ) -> dict[str, Any]:
        before = self.policy_snapshot()
        request: dict[str, Any] = {
            "policyEngineId": self.state["created"]["policy_engine"],
            "policyId": self.form["budget_id"],
            "validationMode": self.form["mode"],
        }
        if statement is not None:
            request["definition"] = {"policy": {"statement": statement}}
        if description is not None:
            request["description"] = description
        requested = _now()
        response = self.ctl.update_policy(**request)
        polls, stable = [], 0
        expected = _digest(statement) if statement is not None else before["statement_sha256"]
        polling = self.protocol["polling"]
        for index in range(polling["max_polls"]):
            time.sleep(polling["interval_seconds"])
            snapshot = {**self.policy_snapshot(), "poll_index": index}
            polls.append(snapshot)
            if snapshot["status"] in {"UPDATE_FAILED", "CREATE_FAILED"}:
                raise RuntimeError(f"policy update failed: {snapshot['status_reasons']}")
            if snapshot["status"] != "ACTIVE":
                stable = 0
                continue
            if (
                snapshot["updated_at"] != before["updated_at"]
                and snapshot["statement_sha256"] == expected
            ):
                break
            stable += 1
            if stable >= STABLE_ACTIVE_POLLS and snapshot["updated_at"] == before["updated_at"]:
                break
        else:
            raise RuntimeError("policy did not settle before the poll bound")
        after = polls[-1]
        return {
            "requested": requested,
            "before": before,
            "submitted": {
                "operation": "UpdatePolicy",
                "definition_supplied": statement is not None,
                "statement_sha256": _digest(statement) if statement is not None else None,
                "description": description,
                "validation_mode": self.form["mode"],
            },
            "managed_response": {
                "status": response.get("status"),
                "updated_at": response["updatedAt"].isoformat(),
            },
            "polls": polls,
            "completed": _now(),
            "after": after,
            "revision_changed": after["updated_at"] != before["updated_at"],
        }

    def select_form(self) -> None:
        validation, descriptions = self.protocol["validation"], self.protocol["descriptions"]
        attempts = []
        for candidate in validation["candidates"][: validation["max_candidates"]]:
            attempt: dict[str, Any] = {"candidate": candidate["id"], "steps": []}
            created: list[str] = []
            try:
                permit_id = None
                if candidate["companion"] is not None:
                    permit_id = self._create_policy(
                        "ContinuationPermit",
                        self._statement(candidate["companion"]),
                        "Continuation evidence permit",
                        FAIL,
                    )
                    created.append(permit_id)
                    attempt["steps"].append("companion validated")
                base = self._statement(candidate["base"])
                budget_id = self._create_policy(
                    "ContinuationBudget", base, descriptions["D0"], FAIL
                )
                created.append(budget_id)
                attempt["steps"].append("base validated")
                self.form = {"mode": FAIL, "budget_id": budget_id}
                for label, text in (
                    ("renamed", self._statement(candidate["renamed"])),
                    ("whitespace", self._whitespace(base)),
                    ("tightened", self._statement(candidate["tightened"])),
                    ("base", base),
                ):
                    self.update(statement=text)
                    attempt["steps"].append(f"{label} validated")
            except (botocore.exceptions.ClientError, RuntimeError) as exc:
                attempt["validated"] = False
                attempt["error"] = _error(exc)
                attempts.append(attempt)
                for policy_id in created:
                    self._delete_policy(policy_id)
                continue
            attempt["validated"] = True
            attempts.append(attempt)
            self.form = {
                "mode": FAIL,
                "candidate": candidate,
                "permit_id": permit_id,
                "budget_id": budget_id,
            }
            self.state["validation"] = attempts
            self._save()
            return
        fallback = validation["candidates"][0]
        permit_id = self._create_policy(
            "ContinuationPermit",
            self._statement(fallback["companion"]),
            "Continuation evidence permit",
            IGNORE,
        )
        budget_id = self._create_policy(
            "ContinuationBudget", self._statement(fallback["base"]), descriptions["D0"], IGNORE
        )
        self.form = {
            "mode": IGNORE,
            "candidate": fallback,
            "permit_id": permit_id,
            "budget_id": budget_id,
        }
        self.state["validation"] = attempts
        self._save()

    def call(self, session_id: str, identifier: str, amount: int) -> dict[str, Any]:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": identifier,
                "method": "tools/call",
                "params": {"name": TOOL, "arguments": {"amount": amount}},
            },
            separators=(",", ":"),
        ).encode()
        request = botocore.awsrequest.AWSRequest(
            method="POST",
            url=self.state["gateway_url"],
            data=body,
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                "mcp-protocol-version": "2025-03-26",
                "x-amzn-bedrock-agentcore-policy-session-id": session_id,
            },
        )
        credentials = self.session.get_credentials().get_frozen_credentials()
        botocore.auth.SigV4Auth(credentials, "bedrock-agentcore", REGION).add_auth(request)
        prepared = request.prepare()
        wire = urllib.request.Request(
            prepared.url, data=prepared.body, headers=dict(prepared.headers), method="POST"
        )
        started = _now()
        try:
            with urllib.request.urlopen(wire, timeout=60) as reply:
                payload, status = reply.read(), reply.status
        except urllib.error.HTTPError as exc:
            payload, status = exc.read(), exc.code
        finished = _now()
        try:
            response = json.loads(payload)
        except json.JSONDecodeError:
            response = {"non_json_body": payload.decode(errors="replace")[:500]}
        if response.get("result", {}).get("isError") is False:
            outcome = "allow"
        else:
            code = response.get("error", {}).get("code")
            outcome = {-32002: "deny", -32005: "stale_session"}.get(code, "error")
        return {
            "session_id": session_id,
            "started": started,
            "finished": finished,
            "http_status": status,
            "request": json.loads(body),
            "response": response,
            "derived_outcome": outcome,
        }

    def ensure_base(self) -> dict[str, Any] | None:
        base = self._statement(self.form["candidate"]["base"])
        snapshot = self.policy_snapshot()
        if (
            snapshot["status"] == "ACTIVE"
            and snapshot["statement_sha256"] == _digest(base)
            and snapshot["description"] == self.protocol["descriptions"]["D0"]
        ):
            return None
        return self.update(statement=base, description=self.protocol["descriptions"]["D0"])

    def controls(self, label: str) -> dict[str, Any]:
        reset = self.ensure_base()
        pair = str(uuid.uuid4())
        record = {
            "label": label,
            "reset": reset,
            "single_below": self.call(str(uuid.uuid4()), f"{label}-below", 500),
            "single_boundary": self.call(str(uuid.uuid4()), f"{label}-boundary", 1000),
            "same_session_pair": [
                self.call(pair, f"{label}-pair-first", 600),
                self.call(pair, f"{label}-pair-second", 600),
            ],
        }
        record["matches_prediction"] = (
            record["single_below"]["derived_outcome"] == "allow"
            and record["single_boundary"]["derived_outcome"] == "deny"
            and [item["derived_outcome"] for item in record["same_session_pair"]]
            == ["allow", "deny"]
        )
        return record

    def trial(self, arm: str, index: int) -> dict[str, Any]:
        descriptions = self.protocol["descriptions"]
        candidate = self.form["candidate"]
        record: dict[str, Any] = {"arm": arm, "trial": index, "reset": self.ensure_base()}
        base = self._statement(candidate["base"])
        predecessor, successor = str(uuid.uuid4()), str(uuid.uuid4())
        record["before_call"] = self.call(predecessor, f"{arm}-{index}-before", 600)
        updates = {
            "byte_identical_statement": {"statement": base},
            "bound_variable_renaming": {"statement": self._statement(candidate["renamed"])},
            "whitespace_only": {"statement": self._whitespace(base)},
            "description_only": {"description": descriptions["D1"]},
            "identical_description": {"description": descriptions["D0"]},
            "tightening_to_700": {"statement": self._statement(candidate["tightened"])},
        }
        record["update"] = self.update(**updates[arm])
        record["predecessor_after_call"] = self.call(predecessor, f"{arm}-{index}-after", 600)
        calls = [record["before_call"], record["predecessor_after_call"]]
        if arm != "byte_identical_statement":
            record["recovery_call"] = self.call(successor, f"{arm}-{index}-recovery", 600)
            record["recovery_after_call"] = self.call(
                successor, f"{arm}-{index}-recovery-after", 600
            )
            calls += [record["recovery_call"], record["recovery_after_call"]]
        elapsed = (
            calls[-1]["finished"]["monotonic_ns"] - calls[0]["started"]["monotonic_ns"]
        ) / 1e9
        record["elapsed_monotonic_seconds"] = elapsed
        problems = [
            call["request"]["id"]
            for call in calls
            if call["http_status"] != 200 or call["derived_outcome"] == "error"
        ]
        if elapsed >= self.protocol["clock"]["scored_sequence_limit_seconds"]:
            problems.append("scored sequence exceeded the temporal window")
        record["conforming"] = not problems
        record["nonconforming_reasons"] = problems
        return record

    def cleanup(self) -> list[dict[str, Any]]:
        created, results = self.state["created"], []

        def attempt(kind: str, action: Any) -> None:
            try:
                action()
                results.append({"kind": kind, "verified_absent": True})
            except Exception as exc:  # noqa: BLE001 - cleanup failures are retained
                results.append({"kind": kind, "verified_absent": False, "error": _error(exc)})

        engine = created.get("policy_engine")
        for policy_id in list(created.get("policies", [])):
            attempt("policy", lambda policy_id=policy_id: self._delete_policy(policy_id))
        if created.get("target"):
            attempt(
                "gateway_target",
                lambda: (
                    self.ctl.delete_gateway_target(
                        gatewayIdentifier=created["gateway"], targetId=created["target"]
                    ),
                    _wait_absent(
                        lambda: self.ctl.get_gateway_target(
                            gatewayIdentifier=created["gateway"], targetId=created["target"]
                        ),
                        "Gateway target",
                    ),
                ),
            )
        if created.get("gateway"):
            attempt(
                "gateway",
                lambda: (
                    self.ctl.delete_gateway(gatewayIdentifier=created["gateway"]),
                    _wait_absent(
                        lambda: self.ctl.get_gateway(gatewayIdentifier=created["gateway"]),
                        "Gateway",
                    ),
                ),
            )
        if engine:
            attempt(
                "policy_engine",
                lambda: (
                    self.ctl.delete_policy_engine(policyEngineId=engine),
                    _wait_absent(
                        lambda: self.ctl.get_policy_engine(policyEngineId=engine), "policy engine"
                    ),
                ),
            )
        if created.get("lambda_function"):
            name = created["lambda_function"]
            attempt(
                "lambda",
                lambda: (
                    self.lam.delete_function(FunctionName=name),
                    _wait_absent(lambda: self.lam.get_function(FunctionName=name), "Lambda"),
                ),
            )
            group = f"/aws/lambda/{name}"

            def remove_log_group() -> None:
                try:
                    self.logs.delete_log_group(logGroupName=group)
                except botocore.exceptions.ClientError as exc:
                    if _code(exc) not in ABSENT:
                        raise
                groups = self.logs.describe_log_groups(logGroupNamePrefix=group)["logGroups"]
                if groups:
                    raise RuntimeError("Lambda log group still exists")

            attempt("lambda_log_group", remove_log_group)
        if created.get("lambda_role"):
            role = created["lambda_role"]
            attempt(
                "lambda_role",
                lambda: (
                    self.iam.detach_role_policy(
                        RoleName=role,
                        PolicyArn=LAMBDA_BASIC_POLICY,
                    ),
                    self.iam.delete_role(RoleName=role),
                    _wait_absent(lambda: self.iam.get_role(RoleName=role), "Lambda role"),
                ),
            )
        if created.get("gateway_role"):
            role = created["gateway_role"]
            attempt(
                "gateway_role",
                lambda: (
                    self.iam.delete_role_policy(
                        RoleName=role, PolicyName="ContinuationGatewayExecution"
                    ),
                    self.iam.delete_role(RoleName=role),
                    _wait_absent(lambda: self.iam.get_role(RoleName=role), "Gateway role"),
                ),
            )
        return results


def run(output: Path) -> int:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    live = Live(output, protocol)
    outcome: dict[str, Any] = {"started": _now(), "stopped": None}
    try:
        live.deploy()
        live.select_form()
        outcome["validation_mode"] = live.form["mode"]
        outcome["candidate"] = live.form["candidate"]["id"]
        preflight = live.controls("preflight")
        _write(output / "preflight.json", preflight)
        if not preflight["matches_prediction"]:
            raise StopCampaign("a pre-flight control did not match its prediction")
        arms = list(protocol["arms"])
        order = [
            {"arm": arm, "trial": index}
            for arm in arms
            for index in range(protocol["trials_per_arm"])
        ]
        random.Random(protocol["random_seed"]).shuffle(order)
        _write(output / "order.json", order)
        nonconforming = dict.fromkeys(arms, 0)
        for position, item in enumerate(order, 1):
            try:
                record = live.trial(item["arm"], item["trial"])
            except (botocore.exceptions.ClientError, RuntimeError) as exc:
                record = {**item, "conforming": False, "error": _error(exc)}
            record["order"] = position
            _write(output / f"trial-{position:02d}.json", record)
            if not record["conforming"]:
                nonconforming[item["arm"]] += 1
                if nonconforming[item["arm"]] > 2:
                    raise StopCampaign(f"more than two nonconforming trials in {item['arm']}")
        postflight = live.controls("postflight")
        _write(output / "postflight.json", postflight)
        outcome["postflight_matches_prediction"] = postflight["matches_prediction"]
    except StopCampaign as exc:
        outcome["stopped"] = str(exc)
    except (botocore.exceptions.ClientError, RuntimeError) as exc:
        outcome["stopped"] = f"capture error: {_error(exc)}"
    finally:
        cleanup = live.cleanup()
        _write(output / "cleanup.json", cleanup)
        outcome.update(
            {
                "finished": _now(),
                "cleanup_complete": all(item["verified_absent"] for item in cleanup),
                "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
            }
        )
        _write(output / "run.json", outcome)
    return 3 if outcome["stopped"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        return run(args.output)
    except (OSError, RuntimeError, botocore.exceptions.BotoCoreError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
