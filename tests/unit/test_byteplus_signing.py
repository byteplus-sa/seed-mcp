"""Fixed signing vectors for the standalone infrastructure adapter."""

from datetime import UTC, datetime

import pytest
from scripts.byteplus_deploy.signing import (
    OpenApiCredentials,
    canonical_query_string,
    sign_request,
)


@pytest.mark.parametrize(
    ("service", "action", "version", "session", "signature"),
    [
        (
            "ecs",
            "DescribeInstances",
            "2020-04-01",
            "",
            0x4416B724AE57271DEF75A43AB8A46685958AF2E452032F94D7F41B6C56450147,
        ),
        (
            "ecs",
            "DescribeInstances",
            "2020-04-01",
            "synthetic-session",
            0xA20BAA9BB810500F20D8A6DDFBD2BCFC5DF71A27A8D4DD04F2AC28076BFB19EE,
        ),
        (
            "kms",
            "GetSecretValue",
            "2021-02-18",
            "",
            0xC7660AB306EF9C2A0F6C94B80141EE5D1AF2A0D0C576823FB9E705FC36D6B431,
        ),
        (
            "kms",
            "GetSecretValue",
            "2021-02-18",
            "synthetic-session",
            0xA48321C7956F2EEBCF58D64BEA17C06A670F216D2608AB3F59C7AE3F3C3E4360,
        ),
    ],
)
def test_infrastructure_signatures_match_previous_vectors(
    service: str, action: str, version: str, session: str, signature: int
) -> None:
    headers = sign_request(
        credentials=OpenApiCredentials("synthetic-access", "synthetic-signing", session),
        method="GET",
        host=f"{service}.ap-southeast-1.byteplusapi.com",
        query={"Version": version, "Action": action},
        payload=b"",
        region="ap-southeast-1",
        service=service,
        now=datetime(2026, 11, 16, 1, 2, 3, tzinfo=UTC),
    )
    assert headers["Authorization"].endswith(f"Signature={signature:064x}")
    assert "Content-Type" not in headers
    assert headers.get("X-Security-Token", "") == session
    assert ("x-security-token" in headers["Authorization"]) == bool(session)


def test_query_parameters_are_sorted_and_percent_encoded() -> None:
    assert canonical_query_string({"b": "x y+", "a": "1/2"}) == "a=1%2F2&b=x%20y%2B"
    assert canonical_query_string({}) == ""


def test_infrastructure_credentials_repr_is_fully_redacted() -> None:
    credentials = OpenApiCredentials("synthetic-access", "synthetic-signing", "synthetic-session")
    assert repr(credentials) == "OpenApiCredentials(***)"
