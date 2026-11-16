"""Tool-lane regressions for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import base64
import importlib
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp.tools import ToolResult

from ark_mcp.providers.modelark.schemas import SeedreamProviderResponse
from ark_mcp.providers.modelark.seedance import SeedanceService
from ark_mcp.providers.modelark.seedream import SeedreamService
from ark_mcp.providers.seed_speech.schemas import SeedAudioProviderResponse
from ark_mcp.providers.seed_speech.seed_audio import SeedAudioService
from ark_mcp.tools._parallel import run_variation_batch
from ark_mcp.tools.gen_task_get import GenTaskGetInput, gen_task_get
from ark_mcp.tools.omnihuman_create_task import OmniHumanCreateTaskInput, omnihuman_create_task
from ark_mcp.tools.omnihuman_get_task import OmniHumanGetTaskInput, omnihuman_get_task
from ark_mcp.tools.seed_audio_generate import (
    SeedAudioGenerateInput,
    SeedAudioGenerateOutput,
    seed_audio_generate,
)
from ark_mcp.tools.seedance_create_task import SeedanceCreateTaskInput, seedance_create_task
from ark_mcp.tools.seedream_generate_image import SeedreamGenerateInput, seedream_generate_image
from tests.fixtures.fake_context import FakeContext


def test_persistence_is_opt_in_on_every_transport() -> None:
    assert SeedAudioGenerateInput(text_prompt="A short tone").persist is False
    assert SeedreamGenerateInput(prompt="A blue square").persist is False
    assert OmniHumanGetTaskInput(task_id="task-test").persist_output is False


@pytest.mark.parametrize(
    ("handler", "input_data"),
    [
        (seed_audio_generate, SeedAudioGenerateInput(text_prompt="tone", persist=True)),
        (seedream_generate_image, SeedreamGenerateInput(prompt="square", persist=True)),
        (gen_task_get, GenTaskGetInput(task_ids=["test"], persist_output=True)),
        (omnihuman_get_task, OmniHumanGetTaskInput(task_id="test", persist_output=True)),
    ],
)
async def test_http_persistence_is_rejected_before_provider_calls(
    fake_ctx: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[..., Awaitable[Any]],
    input_data: object,
) -> None:
    runtime = fake_ctx.lifespan_context["runtime"]
    runtime.settings = runtime.settings.model_copy(update={"mcp_transport": "http"})
    module = importlib.import_module(handler.__module__)
    credentials = Mock(side_effect=AssertionError("must reject before credential/provider use"))
    monkeypatch.setattr(module, "provider_api_key", credentials)
    with pytest.raises(ValueError, match=r"HTTP.*persist|persist.*HTTP"):
        await handler(input_data, fake_ctx)
    credentials.assert_not_called()


@pytest.mark.parametrize("field", ["image", "audio"])
async def test_http_artifact_refs_fail_before_resolution(
    fake_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    runtime = fake_ctx.lifespan_context["runtime"]
    runtime.settings = runtime.settings.model_copy(update={"mcp_transport": "http"})
    resolve = AsyncMock(side_effect=AssertionError("must not resolve media"))
    monkeypatch.setattr("ark_mcp.tools.omnihuman_create_task.resolve_media_ref", resolve)
    refs = {"image": "https://example.com/image.png", "audio": "https://example.com/audio.wav"}
    refs[field] = "seed-media://artifacts/stored-test"
    with pytest.raises(ValueError, match=r"artifact.*HTTP|HTTP.*artifact"):
        await omnihuman_create_task(OmniHumanCreateTaskInput(**refs), fake_ctx)
    resolve.assert_not_awaited()


@pytest.mark.parametrize(
    "url", [None, "", "not-a-url", "file:///tmp/audio.wav", "https://[malformed"]
)
@pytest.mark.parametrize("variations", [1, 3])
async def test_undeliverable_audio_is_explicit_and_never_regenerated(
    fake_ctx: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
    url: str | None,
    variations: int,
) -> None:
    generate = AsyncMock(
        return_value=(
            SeedAudioProviderResponse(
                code=0, audio=base64.b64encode(b"synthetic audio").decode(), url=url
            ),
            "synthetic-provider-log",
        )
    )
    monkeypatch.setattr(SeedAudioService, "generate", generate)
    result = await seed_audio_generate(
        SeedAudioGenerateInput(text_prompt="tone", variations=variations, persist=False), fake_ctx
    )
    assert generate.await_count == variations
    request_ids = {call.kwargs["request_id"] for call in generate.await_args_list}
    if variations == 1:
        assert isinstance(result, ToolResult)
        assert result.is_error
        text = result.content[0].text
        assert "NO_DELIVERABLE_OUTPUT" in text
        assert "retryable=False" in text
        assert "synthetic-provider-log" in text
        assert request_ids.pop() in text
    else:
        assert isinstance(result, SeedAudioGenerateOutput)
        assert result.summary is not None
        assert result.summary.succeeded == 0
        assert result.summary.failed == variations
        for item in result.summary.variations:
            assert item.artifact is None
            assert item.request_id in request_ids
            assert item.provider_log_id == "synthetic-provider-log"
            assert item.error is not None
            assert item.error.code == "NO_DELIVERABLE_OUTPUT"
            assert item.error.retryable is False
            assert item.error.request_id == item.request_id


@pytest.mark.parametrize(
    ("module_name", "handler", "input_data", "service", "method"),
    [
        (
            "seed_audio_generate",
            seed_audio_generate,
            SeedAudioGenerateInput(text_prompt="tone", variations=2),
            SeedAudioService,
            "generate",
        ),
        (
            "_seedream_shared",
            seedream_generate_image,
            SeedreamGenerateInput(prompt="square", variations=2),
            SeedreamService,
            "generate",
        ),
        (
            "_seedance_shared",
            seedance_create_task,
            SeedanceCreateTaskInput(prompt="scene", variations=2),
            SeedanceService,
            "create_task",
        ),
    ],
)
async def test_unexpected_variation_errors_use_request_secret_redaction(
    fake_ctx: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    handler: Callable[..., Awaitable[Any]],
    input_data: object,
    service: type,
    method: str,
) -> None:
    redact = Mock(side_effect=lambda text: text.replace("synthetic-canary", "[REDACTED]"))
    monkeypatch.setattr(f"ark_mcp.tools.{module_name}.redact_request_secrets", redact)
    generate = AsyncMock(side_effect=RuntimeError("failed synthetic-canary"))
    monkeypatch.setattr(service, method, generate)
    result = await handler(input_data, fake_ctx)
    assert "synthetic-canary" not in result.model_dump_json()
    assert "[REDACTED]" in result.model_dump_json()
    assert redact.call_count == generate.await_count == 2


async def test_unexpected_gather_errors_use_request_secret_redaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redact = Mock(side_effect=lambda text: text.replace("synthetic-canary", "[REDACTED]"))
    monkeypatch.setattr("ark_mcp.tools._parallel.redact_request_secrets", redact)
    generate = AsyncMock(side_effect=RuntimeError("failed synthetic-canary"))
    result = await run_variation_batch(2, generate, batch_deadline=1)
    assert result.failed == 2
    assert all(item.error.code == "GATHER_ERROR" for item in result.variations)
    assert "synthetic-canary" not in result.model_dump_json()
    assert redact.call_count == 2


@pytest.mark.parametrize("variations", [1, 2])
@pytest.mark.parametrize("product", ["image", "audio"])
async def test_default_outputs_are_urls_without_storage_or_inline_bytes(
    fake_ctx: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
    variations: int,
    product: str,
) -> None:
    runtime = fake_ctx.lifespan_context["runtime"]
    store = runtime.artifact_store
    write = AsyncMock(side_effect=AssertionError("URL-only generation must not write media"))
    monkeypatch.setattr(store, "put_base64", write)
    monkeypatch.setattr(store, "copy_from_trusted_url", write)
    payload = base64.b64encode(b"synthetic-media").decode()
    url = f"https://example.com/{product}"
    if product == "image":
        generate = AsyncMock(
            return_value=(
                SeedreamProviderResponse(data=[{"url": url, "b64_json": payload}]),
                "synthetic-request",
            )
        )
        monkeypatch.setattr(SeedreamService, "generate", generate)
        result = await seedream_generate_image(
            SeedreamGenerateInput(prompt="square", variations=variations), fake_ctx
        )
        refs = (
            result.artifacts
            if variations == 1
            else [item.artifact for item in result.summary.variations]
        )
    else:
        generate = AsyncMock(
            return_value=(
                SeedAudioProviderResponse(code=0, url=url, audio=payload),
                "synthetic-log",
            )
        )
        monkeypatch.setattr(SeedAudioService, "generate", generate)
        result = await seed_audio_generate(
            SeedAudioGenerateInput(text_prompt="tone", variations=variations), fake_ctx
        )
        refs = (
            [result.artifact]
            if variations == 1
            else [item.artifact for item in result.summary.variations]
        )
    assert len(refs) == variations
    assert all(ref.id == "provider-url" and ref.uri == url for ref in refs)
    assert all(ref.fallback_data is None and ref.persistence_error is None for ref in refs)
    assert generate.await_count == variations
    write.assert_not_awaited()
