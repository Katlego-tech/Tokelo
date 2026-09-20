"""DynamoDB Local in Docker, with this project's two tables in it (docs/design/domain-model.md
§9). The real thing costs money and needs an account; the engine here is Amazon's own, so the
condition expressions and the key design are exercised as they are in staging.

The image is pinned by digest, like every other image this project runs."""

import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

IMAGE = (
    "amazon/dynamodb-local:3.1.0"
    "@sha256:7ef4a2c45b58c2901e70a4f28e0953a422c2c631baaaf5e2c15e0805740c7752"
)
TABLE = "tokelo-test"
AUDIT_TABLE = "tokelo-test-audit"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def dynamodb_local() -> Iterator[str]:
    """The endpoint DynamoDB Local answers on, for this test session only."""
    if not subprocess.run(["which", "docker"], capture_output=True).stdout:
        pytest.skip("docker isn't on PATH, so DynamoDB Local can't run")
    port = free_port()
    name = f"tokelo-dynamodb-{uuid.uuid4().hex[:8]}"
    started = subprocess.run(
        ["docker", "run", "--rm", "-d", "--name", name, "-p", f"{port}:8000", IMAGE],
        capture_output=True,
        text=True,
    )
    assert started.returncode == 0, started.stderr
    endpoint = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.2)
        else:
            raise AssertionError(f"DynamoDB Local didn't answer on {endpoint} within a minute")
        yield endpoint
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture
def store(dynamodb_local: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A Store on two empty tables, made as infra/modules/tokelo-env/tables.tf makes them."""
    import boto3

    from tokelo.core.store import Store

    # Lambda sets all of these; a CI runner has no AWS config file at all, so the test says what
    # a function would be told. Both region variables: botocore reads AWS_DEFAULT_REGION.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("TOKELO_TABLE", TABLE)
    monkeypatch.setenv("TOKELO_AUDIT_TABLE", AUDIT_TABLE)

    dynamodb: Any = boto3.resource("dynamodb", endpoint_url=dynamodb_local, region_name="eu-west-1")
    for name in (TABLE, AUDIT_TABLE):
        table = dynamodb.create_table(
            TableName=name,
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
        )
        table.wait_until_exists()
    try:
        yield Store(endpoint_url=dynamodb_local)
    finally:
        for name in (TABLE, AUDIT_TABLE):
            dynamodb.Table(name).delete()
