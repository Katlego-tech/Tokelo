"""realm railway: the Railway deploy adapter (DESIGN.md §5.2), over Railway's public GraphQL API.

    realm railway deploy <env> <service> <ref>   source mode: <ref> is the commit Railway builds
                                                 image mode: <ref> is the image, by digest
    realm railway live <env> <service>           the commit or image of its last good deploy
    realm railway url <env> <service>            the service's URL in that environment
    realm railway health <env> <service>         its deployment is running (status SUCCESS)

realm.toml: [deploy] staging and production hold the two Railway environments' IDs; each
[[service]] has railway_service (its ID) and, unless it's a worker, staging_url / production_url.
RAILWAY_API_TOKEN is an account or workspace token, sent as a Bearer token; RAILWAY_API_URL
replaces the endpoint (tests).

The calls were checked against Railway's published schema (2026-09-14), not a live account:
serviceInstanceDeployV2 builds a commit, serviceInstanceUpdate sets an image source, and a
deployment's meta carries commitHash or image. Standard library only.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://backboard.railway.com/graphql/v2"
DEPLOY = (
    "mutation($s: String!, $e: String!, $c: String) "
    "{ serviceInstanceDeployV2(serviceId: $s, environmentId: $e, commitSha: $c) }"
)
SET_IMAGE = (
    "mutation($s: String!, $e: String!, $i: ServiceInstanceUpdateInput!) "
    "{ serviceInstanceUpdate(serviceId: $s, environmentId: $e, input: $i) }"
)
STATUS = "query($id: String!) { deployment(id: $id) { id status meta } }"
LATEST = (
    "query($s: String!, $e: String!) { deployments(first: 1, input: {serviceId: $s, "
    "environmentId: $e, status: {in: [SUCCESS]}}) { edges { node { id meta } } } }"
)
DONE = {"SUCCESS"}
BROKEN = {"FAILED", "CRASHED", "REMOVED", "SKIPPED"}


class RailwayError(Exception):
    """A deploy that didn't happen, and why."""


def call(query: str, variables: dict) -> dict:
    token = os.environ.get("RAILWAY_API_TOKEN", "")
    if not token:
        raise RailwayError(
            "RAILWAY_API_TOKEN isn't set: an account or workspace token from "
            "railway.com/account/tokens, kept in the CI secrets"
        )
    url = os.environ.get("RAILWAY_API_URL", API)
    if urllib.parse.urlsplit(url).scheme not in ("https", "http"):
        raise RailwayError(f"refusing a non-web API URL: {url}")  # file:// would read local files
    request = urllib.request.Request(
        url,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        # The scheme was checked above (http(s) only); Semgrep can't see that.
        with urllib.request.urlopen(request, timeout=30) as response:  # nosemgrep
            data = json.load(response)
    except urllib.error.HTTPError as e:
        raise RailwayError(f"Railway's API answered {e.code}: {e.read()[:200]!r}") from e
    except urllib.error.URLError as e:
        raise RailwayError(f"couldn't reach Railway's API: {e.reason}") from e
    if data.get("errors"):
        raise RailwayError("; ".join(str(e.get("message")) for e in data["errors"]))
    return data["data"]


def target(config: dict, env: str, service: str) -> tuple[str, str, dict]:
    deploy = config.get("deploy", {})
    environment = str(deploy.get(env, ""))
    if env not in ("staging", "production") or not environment:
        raise RailwayError(f"realm.toml [deploy] {env} needs the Railway environment's ID")
    svc = next((s for s in config.get("service", []) if s.get("name") == service), None)
    if svc is None or not svc.get("railway_service"):
        raise RailwayError(f"[[service]] {service} needs railway_service (its Railway ID)")
    return str(svc["railway_service"]), environment, svc


def deploy(config: dict, env: str, service: str, ref: str) -> str:
    service_id, environment, _ = target(config, env, service)
    mode = config.get("deploy", {}).get("mode", "source")
    if mode == "image":
        call(SET_IMAGE, {"s": service_id, "e": environment, "i": {"source": {"image": ref}}})
        deployment = call(DEPLOY, {"s": service_id, "e": environment, "c": None})
    else:
        deployment = call(DEPLOY, {"s": service_id, "e": environment, "c": ref})
    deployment_id = deployment["serviceInstanceDeployV2"]
    deadline = time.monotonic() + float(os.environ.get("REALM_RAILWAY_TIMEOUT", "900"))
    while True:
        status = call(STATUS, {"id": deployment_id})["deployment"]["status"]
        if status in DONE:
            return deployment_id
        if status in BROKEN:
            raise RailwayError(f"{service}'s deploy to {env} ended {status} ({deployment_id})")
        if time.monotonic() > deadline:
            raise RailwayError(f"{service}'s deploy to {env} is still {status} after the timeout")
        time.sleep(float(os.environ.get("REALM_RAILWAY_POLL", "5")))


def live(config: dict, env: str, service: str) -> str:
    service_id, environment, _ = target(config, env, service)
    edges = call(LATEST, {"s": service_id, "e": environment})["deployments"]["edges"]
    if not edges:
        raise RailwayError(f"{service} has no successful deploy in {env} yet")
    meta = edges[0]["node"].get("meta") or {}
    mode = config.get("deploy", {}).get("mode", "source")
    value = meta.get("image") if mode == "image" else meta.get("commitHash")
    if not value:
        raise RailwayError(
            f"{service}'s last deploy in {env} doesn't say which "
            f"{'image' if mode == 'image' else 'commit'} it runs"
        )
    return str(value)


def health(config: dict, env: str, service: str) -> str:
    """A worker's health: Railway keeps a service's running deployment at SUCCESS, and marks it
    CRASHED when its process dies (or REMOVED once it's replaced)."""
    service_id, environment, _ = target(config, env, service)
    edges = call(LATEST, {"s": service_id, "e": environment})["deployments"]["edges"]
    if not edges:
        raise RailwayError(f"{service} has no running deployment (SUCCESS) in {env}")
    return f"deployment {edges[0]['node']['id']} is running (SUCCESS)"


def url(config: dict, env: str, service: str) -> str:
    _, _, svc = target(config, env, service)
    if svc.get("kind") == "worker":
        raise RailwayError(f"{service} is a worker: it has no URL")
    value = str(svc.get(f"{env}_url", "")).rstrip("/")
    if not value.startswith("https://"):
        raise RailwayError(f"[[service]] {service} needs {env}_url, its https:// address")
    return value


def cli(config: dict, args: list[str]) -> int:
    if len(args) < 3 or args[0] not in ("deploy", "live", "url", "health"):
        print("usage: realm railway deploy|live|url|health <env> <service> [ref]")
        return 2
    action, env, service, *rest = args
    try:
        if action == "deploy":
            if not rest:
                raise RailwayError("deploy needs the commit or image to deploy")
            print(deploy(config, env, service, rest[0]))
        elif action == "live":
            print(live(config, env, service))
        elif action == "health":
            print(health(config, env, service))
        else:
            print(url(config, env, service))
    except RailwayError as e:
        print(f"!! railway: {e}")
        return 1
    return 0
