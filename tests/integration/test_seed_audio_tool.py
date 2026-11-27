"""Integration tests for the ``seed_audio_generate`` tool handler.

Exercises the full path: input validation → provider call (mocked) →
artifact persistence → structured output.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.tools import ToolResult

from ark_mcp.artifacts.store import ArtifactPersistenceError
from ark_mcp.domain.errors import ProviderError
from ark_mcp.providers.seed_speech.schemas import SeedAudioProviderResponse
from ark_mcp.providers.seed_speech.seed_audio import SeedAudioService
from ark_mcp.tools.seed_audio_generate import (
    SeedAudioGenerateInput,
    SeedAudioGenerateOutput,
    seed_audio_generate,
)
from tests.fixtures.fake_context import FakeContext

SPEECH_BASE = "https://voice.test.example.com"


def _patch_audio_service(monkeypatch: pytest.MonkeyPatch, response_data: dict[str, Any]) -> None:
    """Patch SeedAudioService.generate to return a fixed response."""

    async def mock_generate(
        self: SeedAudioService,
        request: Any,
        *,
        request_id: str | None = None,
    ) -> tuple[Any, str | None]:
        from ark_mcp.providers.seed_speech.schemas import (
            SeedAudioProviderResponse,
        )

        response = SeedAudioProviderResponse.model_validate(response_data)
        return response, "log-test-123"

    monkeypatch.setattr(SeedAudioService, "generate", mock_generate)


class TestSeedAudioGenerateTool:
    """Full-path integration tests for seed_audio_generate."""

    @pytest.mark.parametrize("variations", [1, 2])
    async def test_large_inline_output_persists_without_provider_url(
        self,
        fake_ctx: FakeContext,
        temp_store: Any,
        monkeypatch: pytest.MonkeyPatch,
        variations: int,
    ) -> None:
        raw = b"a" * (10 * 1024 * 1024 + 1)
        _patch_audio_service(
            monkeypatch, {"audio": base64.b64encode(raw).decode(), "duration": 120}
        )
        result = await seed_audio_generate(
            SeedAudioGenerateInput(
                text_prompt="A calm soundscape.", persist=True, variations=variations
            ),
            fake_ctx,
        )
        assert isinstance(result, SeedAudioGenerateOutput)
        artifacts = (
            [item.artifact for item in result.summary.variations]
            if result.summary is not None
            else [result.artifact]
        )
        for artifact in artifacts:
            assert artifact is not None
            assert artifact.uri.startswith("seed-media://artifacts/")
            assert artifact.persistence_error is None
            assert artifact.bytes == len(raw)
            assert (await temp_store.get(artifact.id)).data == raw

    @pytest.mark.parametrize(
        ("output", "expected_mime"),
        [
            (None, "audio/wav"),
            ({}, "audio/wav"),
            ({"format": "wav"}, "audio/wav"),
            ({"format": "mp3"}, "audio/mpeg"),
            ({"format": "ogg"}, "audio/ogg"),
            ({"format": "pcm"}, "audio/pcm"),
        ],
    )
    @pytest.mark.parametrize("variations", [1, 2])
    @pytest.mark.parametrize("delivery", ["url", "persisted", "fallback_url", "fallback_inline"])
    async def test_output_mime_tracks_format_on_every_delivery_path(
        self,
        fake_ctx: FakeContext,
        temp_store: Any,
        monkeypatch: pytest.MonkeyPatch,
        output: dict[str, str] | None,
        expected_mime: str,
        variations: int,
        delivery: str,
    ) -> None:
        audio_b64 = base64.b64encode(b"synthetic audio").decode()
        generate = AsyncMock(
            return_value=(
                SeedAudioProviderResponse(
                    audio=audio_b64,
                    url=None if delivery == "fallback_inline" else "https://example.com/audio",
                ),
                "log-format",
            )
        )
        monkeypatch.setattr(SeedAudioService, "generate", generate)
        monkeypatch.setattr(SeedAudioService, "close", AsyncMock())
        if delivery.startswith("fallback"):
            monkeypatch.setattr(
                temp_store,
                "put_base64",
                AsyncMock(
                    side_effect=ArtifactPersistenceError(
                        "storage_failed", "Synthetic storage failure.", retryable=False
                    )
                ),
            )

        result = await seed_audio_generate(
            SeedAudioGenerateInput(
                text_prompt="tone", output=output, variations=variations, persist=delivery != "url"
            ),
            fake_ctx,
        )

        assert isinstance(result, SeedAudioGenerateOutput)
        artifacts = (
            [result.artifact]
            if variations == 1
            else [item.artifact for item in result.summary.variations]
        )
        for artifact in artifacts:
            assert artifact is not None
            assert artifact.mime_type == expected_mime
            if delivery == "persisted":
                stored = await temp_store.get(artifact.id)
                assert stored.mime_type == expected_mime
                assert stored.data == b"synthetic audio"
            elif delivery == "fallback_inline":
                assert artifact.uri == f"data:{expected_mime};base64,"
                assert artifact.fallback_data == audio_b64
                assert artifact.persistence_error is not None
            else:
                assert artifact.id == "provider-url"
                assert (artifact.persistence_error is not None) == (delivery == "fallback_url")
        assert generate.await_count == variations
        assert all(call.args[0].audio_config == output for call in generate.await_args_list)

    async def test_text_only_generation_with_persistence(
        self,
        test_env: None,
        fake_ctx: FakeContext,
        temp_store: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        audio_b64 = base64.b64encode(b"fake audio data").decode()
        _patch_audio_service(
            monkeypatch,
            {
                "code": 0,
                "message": "success",
                "audio": audio_b64,
                "duration": 2.5,
                "original_duration": 3.0,
                "url": "https://example.com/audio.wav",
            },
        )

        with patch("ark_mcp.artifacts.registry.get_artifact_store", return_value=temp_store):
            result = await seed_audio_generate(
                SeedAudioGenerateInput(text_prompt="Hello world", persist=True), fake_ctx
            )

        assert isinstance(result, SeedAudioGenerateOutput)
        assert result.provider == "byteplus-seed-speech"
        assert result.model == "seed-audio-1.0"
        assert result.duration_seconds == 2.5
        assert result.billing_duration_seconds == 3.0
        assert result.provider_log_id == "log-test-123"
        assert result.artifact.id != "provider-url"
        assert result.artifact.uri.startswith("seed-media://artifacts/")
        assert result.artifact.media_type == "audio"

        # Verify artifact was actually stored.
        stored = await temp_store.get(result.artifact.id)
        assert stored.data == b"fake audio data"
        assert stored.mime_type == "audio/wav"

    async def test_url_only_no_persistence(
        self,
        test_env: None,
        fake_ctx: FakeContext,
        temp_store: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_audio_service(
            monkeypatch,
            {
                "code": 0,
                "message": "success",
                "audio": None,
                "duration": 1.5,
                "original_duration": 2.0,
                "url": "https://example.com/audio.wav",
            },
        )

        with patch("ark_mcp.artifacts.registry.get_artifact_store", return_value=temp_store):
            result = await seed_audio_generate(
                SeedAudioGenerateInput(text_prompt="Hello", persist=True), fake_ctx
            )

        # No base64 audio → falls back to provider URL ref.
        assert result.artifact.id == "provider-url"
        assert result.artifact.uri == "https://example.com/audio.wav"

    async def test_progress_reporting(
        self,
        test_env: None,
        fake_ctx: FakeContext,
        temp_store: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        audio_b64 = base64.b64encode(b"hi").decode()
        _patch_audio_service(
            monkeypatch,
            {"code": 0, "audio": audio_b64, "duration": 1.0, "original_duration": 1.0},
        )

        with patch("ark_mcp.artifacts.registry.get_artifact_store", return_value=temp_store):
            await seed_audio_generate(
                SeedAudioGenerateInput(text_prompt="Hi", persist=True), fake_ctx
            )

        # Should have reported progress at 10, 30, 50, 80, 100.
        progresses = [p for p, _ in fake_ctx.progress_reports]
        assert 10 in progresses
        assert 30 in progresses
        assert 50 in progresses
        assert 80 in progresses
        assert 100 in progresses

    async def test_provider_error_propagates(
        self,
        test_env: None,
        fake_ctx: FakeContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ark_mcp.domain.errors import NormalizedProviderError

        async def mock_generate(
            self: SeedAudioService,
            request: Any,
            *,
            request_id: str | None = None,
        ) -> tuple[Any, str | None]:
            raise ProviderError(
                NormalizedProviderError(
                    provider="seed-speech",
                    operation="generate_audio",
                    http_status=400,
                    code="INVALID_PARAM",
                    message="text too long",
                    retryable=False,
                )
            )

        monkeypatch.setattr(SeedAudioService, "generate", mock_generate)

        result = await seed_audio_generate(SeedAudioGenerateInput(text_prompt="test"), fake_ctx)
        assert isinstance(result, ToolResult)
        assert result.is_error
        assert result.structured_content is None
        text = result.content[0].text
        assert "seed-speech generate_audio failed" in text
        assert "code=INVALID_PARAM" in text
