"""realm aws: the AWS deploy adapter (DESIGN.md §14.3), over the AWS CLI v2.

    realm aws deploy <env> <service> <image@digest>   ECS: the family's latest task definition,
                                                      with that image; Lambda: a new version,
                                                      then live
    realm aws live <env> <service>                    the image the service runs now
    realm aws url <env> <service>                     a web service's URL in that environment
    realm aws health <env> <service>                  ECS: running tasks equal desired, and
                                                      the rollout completed; Lambda: live answers
                                                      the health call

realm.toml: [deploy] region; each [[service]] has runtime = "ecs" or "lambda" and, unless it's a
worker, staging_url / production_url. Names follow the kit's Terraform modules, so realm.toml
holds no resource IDs: ECS cluster <name>-<env>, service and task family <name>-<env>-<service>,
its container <service>; Lambda function <name>-<env>-<service>, alias live.

A Lambda's health call is the payload {"realm": "health"}; the app answers {"ok": true} once it
has started (docs/release/README.md). The CLI signs in as it would anyway: AWS_PROFILE on a
laptop, the release workflow's OIDC session in CI. REALM_AWS_POLL and REALM_AWS_TIMEOUT set the
polling (10 s, up to 900 s). The calls and fields were checked against the service models of the
AWS CLI 2.36.48 (2026-09-18), not a live account. Standard library only.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

RUNTIMES = ("ecs", "lambda")
# describe-task-definition's fields that register-task-definition doesn't take.
READ_ONLY = {
    "taskDefinitionArn",
    "revision",
    "status",
    "requiresAttributes",
    "compatibilities",
    "registeredAt",
    "registeredBy",
    "deregisteredAt",
    "deleteRequestedAt",
}
HEALTH_CALL = {"realm": "health"}
HEALTHY = {"ok": True}


class AwsError(Exception):
    """A deploy or check that didn't succeed, and why."""


@dataclass
class Target:
    region: str
    env: str
    service: str
    runtime: str
    settings: dict
    cluster: str  # ECS only
    resource: str  # the ECS service and task family, or the Lambda function


def target(config: dict, env: str, service: str) -> Target:
    if env not in ("staging", "production"):
        raise AwsError(f"environment {env!r}: staging or production")
    region = str(config.get("deploy", {}).get("region", ""))
    if not region:
        raise AwsError("realm.toml [deploy] needs region, e.g. eu-west-1")
    svc = next((s for s in config.get("service", []) if s.get("name") == service), None)
    if svc is None:
        raise AwsError(f"no [[service]] called {service!r}")
    runtime = str(svc.get("runtime", ""))
    if runtime not in RUNTIMES:
        raise AwsError(f'[[service]] {service} needs runtime = "ecs" or "lambda"')
    name = config["realm"]["name"]
    return Target(region, env, service, runtime, svc, f"{name}-{env}", f"{name}-{env}-{service}")


def aws(t: Target, *args: str) -> dict:
    """One AWS CLI call in the project's region; its JSON answer ({} when it prints none)."""
    try:
        result = subprocess.run(
            ["aws", *args, "--output", "json", "--region", t.region],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise AwsError("the AWS CLI v2 isn't on PATH (GitHub's runners have it)") from None
    if result.returncode != 0:
        said = [line for line in result.stderr.strip().splitlines() if line.strip()]
        raise AwsError(
            f"aws {args[0]} {args[1]}: {said[-1] if said else 'exit ' + str(result.returncode)}"
        )
    try:
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        raise AwsError(f"aws {args[0]} {args[1]} didn't answer in JSON") from None


def poll() -> tuple[float, float]:
    """(seconds between checks, the deadline) from REALM_AWS_POLL and REALM_AWS_TIMEOUT."""
    every = float(os.environ.get("REALM_AWS_POLL", "10"))
    return every, time.monotonic() + float(os.environ.get("REALM_AWS_TIMEOUT", "900"))


# ---------------------------------------------------------------------- ECS ---
def ecs_service(t: Target) -> dict:
    found = aws(t, "ecs", "describe-services", "--cluster", t.cluster, "--services", t.resource)
    services = [s for s in found.get("services", []) if s.get("status") == "ACTIVE"]
    if not services:
        raise AwsError(
            f"no ECS service {t.resource} in cluster {t.cluster}: apply the infrastructure first"
        )
    return services[0]


def primary(service: dict) -> dict:
    found = [d for d in service.get("deployments", []) if d.get("status") == "PRIMARY"]
    if not found:
        raise AwsError(f"{service.get('serviceName')} has no PRIMARY deployment")
    return found[0]


def recent_events(service: dict) -> str:
    """The service's last five events (ECS lists the newest first)."""
    return "; ".join(e.get("message", "") for e in service.get("events", [])[:5])


def deploy_ecs(t: Target, image: str) -> str:
    ecs_service(t)  # there's a service to deploy to
    # The family's latest revision, not the one running: that way a change Terraform made to the
    # task definition (CPU, memory, variables) goes out with the next release (DESIGN.md §14.2).
    described = aws(
        t, "ecs", "describe-task-definition", "--task-definition", t.resource, "--include", "TAGS"
    )
    latest = described["taskDefinition"]["taskDefinitionArn"]
    spec = {k: v for k, v in described["taskDefinition"].items() if k not in READ_ONLY}
    containers = [c for c in spec.get("containerDefinitions", []) if c.get("name") == t.service]
    if not containers:
        raise AwsError(f"task definition {latest} has no container named {t.service}")
    containers[0]["image"] = image
    if described.get("tags"):
        spec["tags"] = described["tags"]
    registered = aws(t, "ecs", "register-task-definition", "--cli-input-json", json.dumps(spec))
    revision = registered["taskDefinition"]["taskDefinitionArn"]
    aws(
        t,
        "ecs",
        "update-service",
        "--cluster",
        t.cluster,
        "--service",
        t.resource,
        "--task-definition",
        revision,
    )
    every, deadline = poll()
    while True:
        service = ecs_service(t)
        deployment = primary(service)
        if deployment.get("taskDefinition") != revision:
            # services-stable would call this stable: the circuit breaker put the old one back.
            raise AwsError(
                f"{t.resource} rolled back to {deployment.get('taskDefinition')}: "
                f"{recent_events(service)}"
            )
        state = deployment.get("rolloutState")
        if state == "FAILED":
            raise AwsError(
                f"{t.resource}'s rollout failed ({deployment.get('rolloutStateReason', '')}): "
                f"{recent_events(service)}"
            )
        running, desired = deployment.get("runningCount"), deployment.get("desiredCount")
        if state == "COMPLETED" and running == desired:
            return revision
        if time.monotonic() > deadline:
            raise AwsError(
                f"{t.resource}'s rollout is still {state} with {running} of {desired} tasks "
                "running, after the timeout"
            )
        time.sleep(every)


def live_ecs(t: Target) -> str:
    revision = primary(ecs_service(t))["taskDefinition"]
    described = aws(t, "ecs", "describe-task-definition", "--task-definition", revision)
    for container in described["taskDefinition"].get("containerDefinitions", []):
        if container.get("name") == t.service:
            return container["image"]
    raise AwsError(f"task definition {revision} has no container named {t.service}")


def health_ecs(t: Target) -> str:
    service = ecs_service(t)
    state = primary(service).get("rolloutState")
    running, desired = service.get("runningCount"), service.get("desiredCount")
    if state != "COMPLETED":
        raise AwsError(f"{t.resource}'s rollout is {state}: {recent_events(service)}")
    if running != desired:
        raise AwsError(f"{t.resource} runs {running} of {desired} tasks: {recent_events(service)}")
    return f"{t.resource}: {running} of {desired} tasks running, rollout completed"


# ------------------------------------------------------------------- Lambda ---
def deploy_lambda(t: Target, image: str) -> str:
    fn = t.resource
    updated = aws(
        t,
        "lambda",
        "update-function-code",
        "--function-name",
        fn,
        "--image-uri",
        image,
        "--publish",
    )
    version = str(updated["Version"])
    every, deadline = poll()
    while True:  # the alias moves only once the new code is Active
        config = aws(
            t, "lambda", "get-function-configuration", "--function-name", fn, "--qualifier", version
        )
        state, update = config.get("State"), config.get("LastUpdateStatus")
        if update == "Failed" or state == "Failed":
            reason = (
                config.get("LastUpdateStatusReason") or config.get("StateReason") or "no reason"
            )
            raise AwsError(f"{fn} version {version} didn't start: {reason}")
        if state == "Active" and update == "Successful":
            break
        if time.monotonic() > deadline:
            raise AwsError(f"{fn} version {version} is still {state} ({update}) after the timeout")
        time.sleep(every)
    aws(
        t,
        "lambda",
        "update-alias",
        "--function-name",
        fn,
        "--name",
        "live",
        "--function-version",
        version,
    )
    return f"{fn}:{version}"


def live_lambda(t: Target) -> str:
    version = aws(t, "lambda", "get-alias", "--function-name", t.resource, "--name", "live")[
        "FunctionVersion"
    ]
    code = aws(
        t, "lambda", "get-function", "--function-name", t.resource, "--qualifier", str(version)
    ).get("Code", {})
    image = code.get("ImageUri") or code.get("ResolvedImageUri")
    if not image:
        raise AwsError(f"{t.resource} version {version} isn't a container image")
    return image


def health_lambda(t: Target) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "answer.json"
        called = aws(
            t,
            "lambda",
            "invoke",
            "--function-name",
            t.resource,
            "--qualifier",
            "live",
            "--cli-binary-format",
            "raw-in-base64-out",
            "--payload",
            json.dumps(HEALTH_CALL),
            str(out),
        )
        answer = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
    version = called.get("ExecutedVersion", "?")
    if called.get("FunctionError"):
        raise AwsError(
            f"{t.resource} (live, version {version}) failed the health call "
            f"({called['FunctionError']}): {answer[:200]}"
        )
    try:
        healthy = json.loads(answer) == HEALTHY
    except json.JSONDecodeError:
        healthy = False
    if not healthy:
        raise AwsError(
            f'{t.resource} (live, version {version}) answered {answer[:200]!r}, not {{"ok": true}}'
        )
    return f'{t.resource} (live, version {version}) answered {{"ok": true}}'


# --------------------------------------------------------------------- verbs ---
def deploy(config: dict, env: str, service: str, image: str) -> str:
    t = target(config, env, service)
    return deploy_ecs(t, image) if t.runtime == "ecs" else deploy_lambda(t, image)


def live(config: dict, env: str, service: str) -> str:
    t = target(config, env, service)
    return live_ecs(t) if t.runtime == "ecs" else live_lambda(t)


def health(config: dict, env: str, service: str) -> str:
    t = target(config, env, service)
    return health_ecs(t) if t.runtime == "ecs" else health_lambda(t)


def url(config: dict, env: str, service: str) -> str:
    t = target(config, env, service)
    if t.settings.get("kind") == "worker":
        raise AwsError(f"{service} is a worker: it has no URL")
    value = str(t.settings.get(f"{env}_url", "")).rstrip("/")
    if not value.startswith("https://"):
        raise AwsError(f"[[service]] {service} needs {env}_url, its https:// address")
    return value


def cli(config: dict, args: list[str]) -> int:
    if len(args) < 3 or args[0] not in ("deploy", "live", "url", "health"):
        print("usage: realm aws deploy|live|url|health <env> <service> [image@digest]")
        return 2
    action, env, service, *rest = args
    try:
        if action == "deploy":
            if not rest:
                raise AwsError("deploy needs the image to deploy, by digest")
            print(deploy(config, env, service, rest[0]))
        else:
            print({"live": live, "url": url, "health": health}[action](config, env, service))
    except AwsError as e:
        print(f"!! aws: {e}")
        return 1
    return 0
