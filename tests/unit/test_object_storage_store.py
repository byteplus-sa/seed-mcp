"""Unit tests for object-storage artifact persistence and access."""

from __future__ import annotations

import base64
from dataclasses import dataclass

import pytest

from ark_mcp.artifacts import object_storage_store
from ark_mcp.artifacts.object_storage_store import ObjectStorageArtifactStore
from ark_mcp.artifacts.store import ArtifactStore
from ark_mcp.domain.artifacts import MediaType
from ark_mcp.security.auth_context import AuthContext
from ark_mcp.security.safe_downloader import SafeDownloadError

PNG_BASE64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 16).decode()


@dataclass
class _Downloaded:
    body: bytes
    content_type: str | None = None


class FakeGateway:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload_bytes(self, *, key: str, data: bytes, mime_type: str) -> None:
        self.objects[key] = data

    async def presign_get(self, *, key: str, expires: int | None = None) -> str:
        return f"https://store.example.com/{key}?sig=abc"

    async def close(self) -> None: ...


class FakeDownloader:
    def __init__(self, gateway: FakeGateway) -> None:
        self._gateway = gateway
        self.trusted_hosts: object = None

    async def download(self, url: str, **kwargs: object) -> _Downloaded:
        if url.startswith("https://media.bytepluses.com/"):
            self.trusted_hosts = kwargs["trusted_hosts"]
            return _Downloaded(b"video-bytes", "video/mp4")
        key = url.split("store.example.com/", 1)[1].split("?", 1)[0]
        if key not in self._gateway.objects:
            raise SafeDownloadError("http_error", "missing", retryable=False)
        return _Downloaded(self._gateway.objects[key])

    async def close(self) -> None: ...


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def downloader(gateway: FakeGateway) -> FakeDownloader:
    return FakeDownloader(gateway)


@pytest.fixture
def store(
    gateway: FakeGateway, downloader: FakeDownloader, monkeypatch: pytest.MonkeyPatch
) -> ObjectStorageArtifactStore:
    monkeypatch.setattr(object_storage_store, "make_object_storage_gateway", lambda _s: gateway)
    return ObjectStorageArtifactStore(downloader=downloader)  # type: ignore[arg-type]


OWNER = AuthContext(principal_id="alice", tenant_id="t1")
OTHER = AuthContext(principal_id="mallory", tenant_id="t1")


class TestObjectStorageArtifactStore:
    def test_object_store_implements_artifact_protocol(
        self, store: ObjectStorageArtifactStore
    ) -> None:
        assert isinstance(store, ArtifactStore)

    async def test_stored_data_and_metadata_are_readable(
        self, store: ObjectStorageArtifactStore, gateway: FakeGateway
    ) -> None:
        ref = await store.put_base64(PNG_BASE64, MediaType.IMAGE, "image/png", auth=OWNER)
        artifact = await store.get(ref.id, auth=OWNER)
        location = await store.locate(ref.id, auth=OWNER)
        expected_key = f"artifacts/{ref.id[:2]}/{ref.id}.png"
        assert gateway.objects[expected_key] == base64.b64decode(PNG_BASE64)
        assert artifact.data == gateway.objects[expected_key]
        assert artifact.mime_type == "image/png"
        assert location.path is None
        assert location.ref == ref

    @pytest.mark.parametrize("method", ["get", "locate"])
    async def test_other_principal_is_rejected(
        self, store: ObjectStorageArtifactStore, method: str
    ) -> None:
        ref = await store.put_base64(PNG_BASE64, MediaType.IMAGE, "image/png", auth=OWNER)
        with pytest.raises(PermissionError):
            await getattr(store, method)(ref.id, auth=OTHER)

    @pytest.mark.parametrize("method", ["get", "locate"])
    async def test_same_principal_id_in_another_tenant_is_rejected(
        self, store: ObjectStorageArtifactStore, method: str
    ) -> None:
        ref = await store.put_base64(PNG_BASE64, MediaType.IMAGE, "image/png", auth=OWNER)
        with pytest.raises(PermissionError):
            await getattr(store, method)(
                ref.id,
                auth=AuthContext(principal_id="alice", tenant_id="t2"),
            )

    @pytest.mark.parametrize("method", ["get", "locate"])
    async def test_unknown_artifact_raises_not_found(
        self, store: ObjectStorageArtifactStore, method: str
    ) -> None:
        with pytest.raises(FileNotFoundError):
            await getattr(store, method)("11111111-1111-4111-8111-111111111111", auth=OWNER)

    @pytest.mark.parametrize("method", ["get", "locate"])
    async def test_malformed_artifact_id_raises_value_error(
        self, store: ObjectStorageArtifactStore, method: str
    ) -> None:
        with pytest.raises(ValueError, match="Invalid artifact ID"):
            await getattr(store, method)("../etc/passwd", auth=OWNER)


class TestTrustedHosts:
    async def test_download_uses_fixed_provider_allowlist(
        self, store: ObjectStorageArtifactStore, downloader: FakeDownloader
    ) -> None:
        await store.copy_from_trusted_url(
            "https://media.bytepluses.com/v.mp4",
            MediaType.VIDEO,
            "video/mp4",
            auth=OWNER,
        )
        predicate = downloader.trusted_hosts
        assert callable(predicate)
        assert predicate("media.bytepluses.com") is True
        assert predicate("MEDIA.BYTEPLUSES.COM") is True
        assert predicate("media.bytepluses.com.attacker.example") is False
        assert predicate("v16m-default.media.example.com") is False
