"""Static MCP tool catalog: the single inventory of registered tools.

Each entry names the tool, the module that implements it, its authorization
scope, and the settings gate that decides whether it
is registered. Entries hold metadata only, so importing the catalog never
imports a tool module; ``load_tool_definitions`` imports the modules whose
gate passes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pydantic import BaseModel

    from ark_mcp.config.env import Settings


def _always(_settings: Settings) -> bool:
    return True


def _local(settings: Settings) -> bool:
    return settings.mcp_transport == "stdio"


def _modelark(settings: Settings) -> bool:
    return settings.mcp_transport == "http" or settings.has_modelark


def _seed_audio(settings: Settings) -> bool:
    return settings.mcp_transport == "http" or settings.has_seed_audio


def _seed_tts(settings: Settings) -> bool:
    return settings.mcp_transport == "http" or settings.has_seed_audio


def _object_storage(settings: Settings) -> bool:
    return _local(settings) and settings.has_object_storage


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """Registration metadata for one MCP tool."""

    name: str
    module: str
    output: str
    scope: str | None
    gate: Callable[[Settings], bool] = _always
    annotations: str = "TOOL_ANNOTATIONS"
    provider: Literal["modelark", "seed-speech"] | None = None


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Runtime objects a catalog entry resolves to."""

    handler: Callable[..., Awaitable[Any]]
    output_model: type[BaseModel]
    annotations: Mapping[str, bool]


def _entry(
    name: str,
    output: str,
    scope: str | None,
    *,
    gate: Callable[[Settings], bool] = _always,
    module: str | None = None,
    annotations: str = "TOOL_ANNOTATIONS",
) -> CatalogEntry:
    return CatalogEntry(
        name=name,
        module=f"ark_mcp.tools.{module or name}",
        output=output,
        scope=scope,
        gate=gate,
        annotations=annotations,
        provider=(
            "modelark"
            if gate is _modelark
            else "seed-speech"
            if gate in (_seed_audio, _seed_tts)
            else None
        ),
    )


CATALOG: tuple[CatalogEntry, ...] = (
    _entry("ark_list_models", "ArkListModelsOutput", None),
    _entry("seed_media_get_artifact", "SeedMediaGetArtifactOutput", "artifacts:read", gate=_local),
    _entry(
        "seed_media_export_artifact", "SeedMediaExportArtifactOutput", "artifacts:read", gate=_local
    ),
    _entry(
        "seed_media_persist_url",
        "SeedMediaPersistUrlOutput",
        "media:upload",
        gate=_local,
    ),
    _entry(
        "seed_audio_generate",
        "SeedAudioGenerateOutput",
        "seed:audio:generate",
        gate=_seed_audio,
    ),
    _entry(
        "seed_tts_generate",
        "SeedTtsGenerateOutput",
        "seed:tts:generate",
        gate=_seed_tts,
    ),
    _entry(
        "media_upload",
        "MediaUploadOutput",
        "media:upload",
        gate=_object_storage,
    ),
    _entry("media_presign", "MediaPresignOutput", "media:presign", gate=_object_storage),
    _entry(
        "ark_file_upload",
        "ManagedFile",
        "files:write",
        gate=_modelark,
        module="ark_files",
        annotations="UPLOAD_ANNOTATIONS",
    ),
    _entry(
        "ark_file_get",
        "ManagedFile",
        "files:read",
        gate=_modelark,
        module="ark_files",
        annotations="READ_ANNOTATIONS",
    ),
    _entry(
        "ark_file_list",
        "FilePage",
        "files:read",
        gate=_modelark,
        module="ark_files",
        annotations="READ_ANNOTATIONS",
    ),
    _entry(
        "ark_file_delete",
        "FileDeleted",
        "files:delete",
        gate=_modelark,
        module="ark_files",
        annotations="DELETE_ANNOTATIONS",
    ),
    _entry(
        "seedream_generate_image",
        "SeedreamGenerateOutput",
        "seedream:generate",
        gate=_modelark,
    ),
    _entry(
        "seedance_create_task",
        "SeedanceCreateTaskOutput",
        "seedance:create",
        gate=_modelark,
    ),
    _entry(
        "gen_task_get",
        "GenTaskGetOutput",
        "gen:read",
        gate=_modelark,
    ),
    _entry("gen_task_list", "GenTaskPage", "gen:read", gate=_modelark),
    _entry(
        "gen_task_cancel_or_delete",
        "GenTaskCancelOrDeleteOutput",
        "gen:delete",
        gate=_modelark,
    ),
)


def catalog_entry(name: str) -> CatalogEntry | None:
    """Return the catalog entry for a tool name, if the tool exists."""
    return _BY_NAME.get(name)


def resolve_tool_definition(entry: CatalogEntry) -> ToolDefinition:
    """Import the entry's module and return its handler, output model and annotations."""
    module = import_module(entry.module)
    return ToolDefinition(
        handler=getattr(module, entry.name),
        output_model=getattr(module, entry.output),
        annotations=getattr(module, entry.annotations),
    )


def load_tool_definitions(settings: Settings) -> list[tuple[CatalogEntry, ToolDefinition]]:
    """Resolve every entry whose gate passes, in catalog order."""
    return [(entry, resolve_tool_definition(entry)) for entry in CATALOG if entry.gate(settings)]


_BY_NAME: Mapping[str, CatalogEntry] = {entry.name: entry for entry in CATALOG}
