"""Regression coverage for Seed Studio's supported service surface."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ark_mcp.config.env import Settings, get_settings
from ark_mcp.config.model_capabilities import refresh_capability_registry
from ark_mcp.domain.artifacts import ArtifactRef, MediaType
from ark_mcp.server import create_server
from ark_mcp.tools._catalog import CATALOG
from ark_mcp.tools.ark_list_models import (
    ArkListModelsInput,
    ArkListModelsOutput,
    ModelInfo,
    ark_list_models,
    describe_services,
)
from ark_mcp.tools.seed_media_persist_url import SeedMediaPersistUrlInput
from ark_mcp.tools.seedream_generate_image import SeedreamGeneratePreview
from tests.fixtures.fake_context import FakeContext

SUPPORTED_TOOLS = {
    "ark_job_capabilities",
    "ark_job_submit",
    "ark_job_get",
    "ark_job_cancel",
    "ark_list_models",
    "seed_media_get_artifact",
    "seed_media_export_artifact",
    "seed_media_persist_url",
    "seed_audio_generate",
    "media_upload",
    "media_presign",
    "omnihuman_create_task",
    "omnihuman_get_task",
    "omnihuman_cancel_task",
    "seedream_generate_image",
    "seedance_create_task",
    "gen_task_get",
    "gen_task_list",
    "gen_task_cancel_or_delete",
    "seed_understand",
    "seed_audio_understand",
}


def test_catalog_exposes_only_seed_studio_services() -> None:
    assert len(CATALOG) == 21
    assert {entry.name for entry in CATALOG} == SUPPORTED_TOOLS


async def test_omnihuman_and_supported_services_register(all_services_enabled: None) -> None:
    server = create_server(get_settings())
    assert {tool.name for tool in await server.list_tools()} == SUPPORTED_TOOLS


async def test_tool_schemas_do_not_advertise_removed_artifact_types(
    all_services_enabled: None,
) -> None:
    server = create_server(get_settings())
    for tool in await server.list_tools():
        assert "three_d" not in json.dumps(tool.parameters), tool.name
        assert "three_d" not in json.dumps(tool.output_schema), tool.name


def test_removed_service_settings_are_not_part_of_configuration() -> None:
    removed = {
        name
        for name in Settings.model_fields
        if name.startswith(
            (
                "vod_",
                "stt_",
                "seed3d_",
                "hyper3d_",
                "hitem3d_",
                "seed_speech_asr_",
                "modelark_asset",
                "modelark_pricing_",
            )
        )
        or name
        in {
            "seed_speech_asr_base_url",
            "modelark_3d_enabled",
            "seed3d_enabled",
            "modelark_access_key",
            "modelark_secret_key",
            "modelark_session_token",
            "modelark_openapi_host",
            "modelark_openapi_base_url",
            "modelark_region",
            "modelark_project_name",
            "modelark_asset_reference_mode",
            "seedance_asset_preflight",
        }
    }
    assert removed == set()


def test_discovery_does_not_offer_removed_services() -> None:
    names = {service.service for service in describe_services(get_settings())}
    assert names == {"modelark", "seed_audio", "omnihuman", "object_storage"}


@pytest.mark.parametrize("kind", ["3d", "audio", "vod", "asr"])
def test_discovery_rejects_unsupported_kinds(kind: str) -> None:
    with pytest.raises(ValidationError):
        ArkListModelsInput.model_validate({"kind": kind})


def test_discovery_schema_has_no_operator_pricing() -> None:
    assert set(ArkListModelsOutput.model_fields) == {"models", "services"}
    assert "pricing" not in ModelInfo.model_fields


def test_artifact_schema_contains_only_retained_media_types() -> None:
    assert set(MediaType) == {"image", "audio", "video"}
    assert ArtifactRef.model_json_schema()["$defs"]["MediaType"]["enum"] == [
        "image",
        "audio",
        "video",
    ]


@pytest.mark.parametrize("media_type", ["3d", "three_d"])
def test_artifact_rejects_removed_media_types(media_type: str) -> None:
    with pytest.raises(ValidationError):
        ArtifactRef(
            id="test-artifact",
            uri="seed-media://artifacts/test-artifact",
            media_type=media_type,
            mime_type="application/octet-stream",
            created_at="2026-11-16T00:00:00Z",
        )


@pytest.mark.parametrize("media_type", ["image", "audio", "video"])
def test_url_persistence_accepts_retained_media_types(media_type: str) -> None:
    request = SeedMediaPersistUrlInput.model_validate(
        {
            "url": "https://cdn.example.com/output",
            "media_type": media_type,
            "mime_type": f"{media_type}/test",
        }
    )
    assert request.media_type == media_type


@pytest.mark.parametrize("media_type", ["3d", "three_d", "", None])
def test_url_persistence_rejects_unsupported_media_types(media_type: str | None) -> None:
    with pytest.raises(ValidationError):
        SeedMediaPersistUrlInput.model_validate(
            {
                "url": "https://cdn.example.com/output",
                "media_type": media_type,
                "mime_type": "application/octet-stream",
            }
        )


def test_preview_schema_advertises_only_builtin_estimates() -> None:
    schema = SeedreamGeneratePreview.model_json_schema()
    assert schema["properties"]["price_source"]["const"] == "builtin"
    preview = SeedreamGeneratePreview(requests=[], estimated_cost_usd=0)
    assert preview.price_source == "builtin"


@pytest.mark.parametrize("source", ["catalog", "live", "account"])
def test_preview_rejects_account_pricing_claims(source: str) -> None:
    with pytest.raises(ValidationError):
        SeedreamGeneratePreview.model_validate(
            {"requests": [], "estimated_cost_usd": 0, "price_source": source}
        )


@pytest.mark.parametrize("kind", [None, "video", "image", "understanding"])
async def test_discovery_is_offline_and_filters_retained_models(
    all_services_enabled: None, kind: str | None
) -> None:
    refresh_capability_registry()
    result = await ark_list_models(ArkListModelsInput.model_validate({"kind": kind}), FakeContext())
    assert result.models
    expected_kinds = {kind} if kind else {"video", "image", "understanding"}
    assert {model.kind for model in result.models} == expected_kinds
    assert all(model.tool in SUPPORTED_TOOLS for model in result.models)
    assert all(service.enabled for service in result.services)
    assert set(result.model_dump()) == {"models", "services"}
    assert all("pricing" not in model.model_dump() for model in result.models)


def test_configured_models_returns_three_retained_maps() -> None:
    registry = refresh_capability_registry()
    image, video, understanding = registry.configured_models()
    assert set(image) == set(registry.list_image_models())
    assert set(video) == set(registry.list_video_models())
    assert set(understanding) == set(registry.list_understanding_models())
