"""PR #133: large inline audio persists without relaxing input or URL limits."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ark_mcp.artifacts import object_storage_store
from ark_mcp.artifacts.filesystem_store import FilesystemArtifactStore
from ark_mcp.artifacts.object_storage_store import ObjectStorageArtifactStore
from ark_mcp.artifacts.store import ArtifactPersistenceError, artifact_limit_bytes
from ark_mcp.domain.artifacts import MediaType
from ark_mcp.security.auth_context import AuthContext
from ark_mcp.security.media_policy import MediaValidationError, decode_base64_safely
from ark_mcp.security.safe_downloader import DownloadedMedia
from ark_mcp.tools._persistence import persist_base64
from tests.unit.test_object_storage_store import FakeDownloader, FakeGateway


@pytest.mark.parametrize("backend", ["filesystem", "object_storage"])
async def test_large_inline_audio_roundtrip_with_owned_size_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    raw = b"a" * (10 * 1024 * 1024 + 1)
    data = base64.b64encode(raw).decode()
    owner = AuthContext(principal_id="alice", tenant_id="t1")
    if backend == "filesystem":
        store = FilesystemArtifactStore(artifact_dir=str(tmp_path))
    else:
        gateway = FakeGateway()
        downloader = FakeDownloader(gateway)
        monkeypatch.setattr(object_storage_store, "make_object_storage_gateway", lambda _: gateway)
        download = AsyncMock(wraps=downloader.download)
        monkeypatch.setattr(downloader, "download", download)
        store = ObjectStorageArtifactStore(downloader=downloader)
    try:
        ref = await store.put_base64(data, MediaType.AUDIO, "audio/wav", auth=owner)
        assert ref.bytes == len(raw)
        assert (await store.get(ref.id, auth=owner)).data == raw
        if backend == "object_storage":
            assert download.call_args.kwargs["max_bytes"] == len(raw)
        with pytest.raises(PermissionError):
            await store.get(ref.id, auth=AuthContext(principal_id="other", tenant_id="t1"))
        with pytest.raises(MediaValidationError):
            decode_base64_safely(data, 10 * 1024 * 1024, label="reference audio")
        with pytest.raises(MediaValidationError):
            await store.put_base64("invalid!", MediaType.AUDIO, "audio/wav")
    finally:
        await store.close()


@pytest.mark.parametrize("backend", ["filesystem", "object_storage"])
async def test_url_audio_still_has_download_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    cap = artifact_limit_bytes(MediaType.AUDIO)
    downloader = AsyncMock()
    downloader.download.return_value = DownloadedMedia(
        body=b"x" * (cap + 1),
        content_type="audio/wav",
        final_url="https://media.bytepluses.com/a.wav",
    )
    if backend == "filesystem":
        store = FilesystemArtifactStore(artifact_dir=str(tmp_path), downloader=downloader)
    else:
        monkeypatch.setattr(
            object_storage_store, "make_object_storage_gateway", lambda _: FakeGateway()
        )
        store = ObjectStorageArtifactStore(downloader=downloader)
    try:
        with pytest.raises(ArtifactPersistenceError) as error:
            await store.copy_from_trusted_url(
                "https://media.bytepluses.com/a.wav", MediaType.AUDIO, "audio/wav"
            )
        assert error.value.code == "output_too_large"
        assert downloader.download.call_args.kwargs["max_bytes"] == 10 * 1024 * 1024
    finally:
        await store.close()


async def test_inline_fallback_metadata_is_nullable_but_fallback_remains_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ark_mcp.config.env import get_settings

    monkeypatch.setenv("ARTIFACT_INLINE_FALLBACK_MAX_BYTES", "4")
    get_settings.cache_clear()
    store = AsyncMock()
    store.put_base64.side_effect = ArtifactPersistenceError(
        "storage_failed", "Storage unavailable.", retryable=False
    )
    ref = await persist_base64(
        store,
        data=base64.b64encode(b"1234").decode(),
        media_type=MediaType.AUDIO,
        mime_type="audio/wav",
        source_expires_at=None,
        auth=None,
    )
    assert ref.persistence_error.artifact_limit_bytes is None
    assert ref.id == "inline-fallback"
    with pytest.raises(ArtifactPersistenceError):
        await persist_base64(
            store,
            data=base64.b64encode(b"12345").decode(),
            media_type=MediaType.AUDIO,
            mime_type="audio/wav",
            source_expires_at=None,
            auth=None,
        )
    url_ref = await persist_base64(
        store,
        data=base64.b64encode(b"12345").decode(),
        media_type=MediaType.AUDIO,
        mime_type="audio/wav",
        source_expires_at=None,
        auth=None,
        provider_url="https://media.bytepluses.com/a.wav",
    )
    assert url_ref.id == "provider-url"
    assert url_ref.persistence_error.artifact_limit_bytes == 10 * 1024 * 1024
