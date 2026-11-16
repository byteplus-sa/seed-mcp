"""Offline schema regressions for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from ark_mcp.config.env import Settings
from ark_mcp.providers.modelark.schemas import ChatCompletionProviderResponse
from ark_mcp.providers.modelark.understanding import SeedUnderstandingService
from ark_mcp.tools import _understanding_shared as shared
from tests.fixtures.fake_context import FakeContext
from tests.integration.test_byok_http import (
    assert_denied,
    call_tool,
    credentials,
    http_server,
    http_settings,
)

REFERENCE_KEYWORDS = ("$ref", "$dynamicRef", "$recursiveRef")
EXTERNAL_REFERENCES = (
    "http://169.254.169.254/latest/meta-data/",
    "https://example.invalid/schema.json",
    "file:///offline-schema-must-not-be-opened.json",
    "//example.invalid/schema.json",
    "/schema.json",
    "schema.json#/$defs/value",
    "",
)


@pytest.fixture(autouse=True)
def no_retrieval(monkeypatch):
    retrieve = Mock(side_effect=AssertionError("Schema validation must not retrieve resources"))
    monkeypatch.setattr("urllib.request.urlopen", retrieve)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", retrieve)
    yield retrieve
    retrieve.assert_not_called()


def response_format(schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": "offline", "schema": schema}}


def unchecked_format(schema: dict[str, Any]) -> shared.UnderstandingResponseFormat:
    return shared.UnderstandingResponseFormat.model_construct(
        type="json_schema",
        json_schema=shared.UnderstandingJsonSchema.model_construct(name="offline", schema_=schema),
    )


@pytest.mark.parametrize("keyword", REFERENCE_KEYWORDS)
@pytest.mark.parametrize("reference", EXTERNAL_REFERENCES)
@pytest.mark.parametrize("nested", [False, True])
def test_nonlocal_references_are_rejected_by_model_preflight(keyword, reference, nested):
    schema = {keyword: reference}
    if nested:
        schema = {"allOf": [{"$defs": {"unused": schema}}]}
    with pytest.raises(ValidationError, match="fragment"):
        shared.UnderstandingResponseFormat.model_validate(response_format(schema))


@pytest.mark.parametrize("keyword", REFERENCE_KEYWORDS)
def test_schema_model_itself_rejects_nonlocal_references(keyword):
    with pytest.raises(ValidationError, match="fragment"):
        shared.UnderstandingJsonSchema.model_validate(
            {"name": "offline", "schema": {keyword: EXTERNAL_REFERENCES[0]}}
        )


@pytest.mark.parametrize("tool_name", ["seed_understand", "seed_audio_understand"])
async def test_http_preflight_denies_schema_before_gateway_dispatch(
    tmp_path, monkeypatch, tool_name
):
    gateway = Mock(side_effect=AssertionError("Invalid schemas must not reach a gateway"))
    monkeypatch.setattr(shared, "modelark_gateway", gateway)
    arguments = {
        "prompt": "Return JSON",
        "response_format": response_format({"$ref": EXTERNAL_REFERENCES[0]}),
    }
    if tool_name == "seed_audio_understand":
        arguments["audios"] = [{"kind": "url", "url": "https://example.com/audio.wav"}]
    async with http_server(tmp_path, settings=http_settings(tmp_path)) as (_, _, client):
        result = await call_tool(client, tool_name, arguments, headers=credentials())
    assert_denied(result)
    gateway.assert_not_called()


@pytest.mark.parametrize("keyword", REFERENCE_KEYWORDS)
@pytest.mark.parametrize("reference", EXTERNAL_REFERENCES[:3])
def test_reply_validation_rejects_unchecked_external_references(keyword, reference):
    parsed, violation = shared._check_json("{}", "stop", unchecked_format({keyword: reference}))
    assert parsed is None
    assert violation is not None
    assert violation.finish_reason == "stop"
    assert reference not in violation.message


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
@pytest.mark.parametrize("reference", EXTERNAL_REFERENCES[:3])
def test_reply_registry_denies_retrieval_even_if_reference_preflight_is_bypassed(
    monkeypatch, keyword, reference
):
    monkeypatch.setattr(shared, "_validate_schema_references", lambda schema: None, raising=False)
    parsed, violation = shared._check_json("{}", "stop", unchecked_format({keyword: reference}))
    assert parsed is None
    assert violation is not None
    assert reference not in violation.message


@pytest.mark.parametrize(
    "dialect",
    ["http://json-schema.org/draft-07/schema#", "https://json-schema.org/draft/2019-09/schema"],
)
def test_nested_dialect_cannot_restore_default_retrieval(monkeypatch, dialect):
    monkeypatch.setattr(shared, "_validate_schema_references", lambda schema: None)
    schema = {"properties": {"answer": {"$schema": dialect, "$ref": EXTERNAL_REFERENCES[2]}}}
    parsed, violation = shared._check_json('{"answer": {}}', "stop", unchecked_format(schema))
    assert parsed is None
    assert violation is not None


@pytest.mark.parametrize(
    "schema",
    [
        {
            "$defs": {"answer": {"type": "object", "required": ["answer"]}},
            "$ref": "#/$defs/answer",
        },
        {
            "$id": "https://example.invalid/root",
            "$defs": {"answer": {"$anchor": "answer", "type": "object", "required": ["answer"]}},
            "$ref": "#answer",
        },
        {
            "$defs": {
                "answer": {"$dynamicAnchor": "answer", "type": "object", "required": ["answer"]}
            },
            "$dynamicRef": "#answer",
        },
        {
            "type": "object",
            "required": ["answer"],
            "properties": {"child": {"$ref": "#"}},
        },
        {
            "type": "object",
            "properties": {"$ref": {"type": "string"}, "$dynamicRef": {"type": "string"}},
            "required": ["answer"],
        },
        {
            "type": "object",
            "required": ["answer"],
            "properties": {"child": {"$recursiveRef": "#"}},
        },
    ],
)
def test_internal_references_validate_success_and_report_mismatch(schema):
    format_model = shared.UnderstandingResponseFormat.model_validate(response_format(schema))
    value = {"answer": 42, "child": {"answer": 7}}
    parsed, violation = shared._check_json(json.dumps(value), "stop", format_model)
    assert parsed == value
    assert violation is None
    parsed, violation = shared._check_json("{}", "length", format_model)
    assert parsed is None
    assert violation is not None
    assert violation.finish_reason == "length"


@pytest.mark.parametrize("reference", ["#/$defs/missing", "#missing", "#"])
def test_unresolvable_or_cyclic_internal_reference_returns_violation(reference):
    format_model = shared.UnderstandingResponseFormat.model_validate(
        response_format({"$ref": reference})
    )
    parsed, violation = shared._check_json("{}", "stop", format_model)
    assert parsed is None
    assert violation is not None


@pytest.mark.parametrize("schema", [{}, {"type": "object"}, {"$defs": {"unused": False}}])
def test_empty_and_reference_free_schemas_remain_supported(schema):
    format_model = shared.UnderstandingResponseFormat.model_validate(response_format(schema))
    assert shared._check_json("{}", "stop", format_model) == ({}, None)


@pytest.mark.parametrize("schema", [{"type": 5}, {"$ref": 5}, {"description": "x" * 65536}])
def test_invalid_or_oversized_schema_is_rejected(schema):
    with pytest.raises(ValidationError):
        shared.UnderstandingResponseFormat.model_validate(response_format(schema))


@pytest.mark.parametrize("schema", [{"$ref": EXTERNAL_REFERENCES[0]}, {"$ref": "#missing"}])
async def test_resolution_violation_preserves_billed_completion(monkeypatch, schema):
    content = '{"answer": 42}'
    response = ChatCompletionProviderResponse.model_validate(
        {
            "id": "chatcmpl-offline",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
    )
    generate = AsyncMock(return_value=(response, "req-offline"))
    close = AsyncMock()
    monkeypatch.setattr(SeedUnderstandingService, "generate", generate)
    monkeypatch.setattr(SeedUnderstandingService, "close", close)
    monkeypatch.setattr(shared, "modelark_gateway", Mock())

    @asynccontextmanager
    async def billed_slot(*args, **kwargs):
        yield

    monkeypatch.setattr(shared, "billed_provider_slot", billed_slot)
    options = shared.UnderstandingOptions.model_construct(
        prompt="Return JSON", response_format=unchecked_format(schema)
    )
    result = await shared.run_understanding(
        options,
        FakeContext(),
        settings=Settings(_env_file=None),
        model_id="dola-seed-2-1-turbo-260628",
        supports_thinking=True,
        output_cls=shared.SeedUnderstandOutput,
    )
    assert isinstance(result, shared.SeedUnderstandOutput)
    assert result.completion_id == "chatcmpl-offline"
    assert result.request_id == "req-offline"
    assert result.usage.total_tokens == 30
    assert result.attempts == 1
    assert result.choices[0].content == content
    assert result.choices[0].schema_violation is not None
    generate.assert_awaited_once()
    close.assert_awaited_once()
