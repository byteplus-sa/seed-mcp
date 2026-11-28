"""Opt-in Seedream 5.5 smoke matrix; no arguments prints offline help.

Example: uv run python scripts/smoke_seedream55.py --execute --confirm-cost 0.20
The USD confirmation caps the aggregate estimate, not the eventual provider bill.
All dry runs finish before any paid case. No submission is retried.
See specs/SPEC_DIRECT_EXECUTION.md and docs/models.md for the contracts.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastmcp import Client

    from ark_mcp.config.env import Settings
    from ark_mcp.tools.seedream_generate_image import SeedreamGenerateInput

BASE_CASES = ("t2i-opaque", "t2i-transparent", "reference-edit", "point-edit", "bbox-edit")
CASE_NAMES = BASE_CASES
REPOSITORY = Path(__file__).resolve().parents[1]
DIMENSIONS = (1024, 1024)


class SmokeFailure(Exception):
    """Carry only a script-owned error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SmokeCase:
    name: str
    request: SeedreamGenerateInput


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--execute", action="store_true", help="Enable the live matrix.")
    result.add_argument(
        "--confirm-cost",
        type=float,
        metavar="USD",
        help="Explicit approved aggregate estimated USD limit; required with --execute.",
    )
    result.add_argument("--model", help="Configured 5.5 model ID; uses the configured default.")
    result.add_argument("--case", action="append", choices=CASE_NAMES, dest="selected")
    result.add_argument(
        "--max-cases",
        type=int,
        default=5,
        help="Hard case cap, 1-5 (default 5); select fewer cases with repeatable --case.",
    )
    result.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY / ".artifacts",
        help="Safe local output root (default .artifacts); a fresh run subdirectory is created.",
    )
    result.add_argument("--timeout", type=float, default=300, help="Seconds per call, 0-1800.")
    return result


def safe_output_directory(directory: Path) -> Path:
    """Validate the destination without creating anything or following user symlinks."""
    if ".." in directory.parts:
        raise SmokeFailure("unsafe_output_directory")
    absolute = directory.expanduser().absolute()
    for component in (absolute, *absolute.parents):
        if component.is_symlink() and component not in (Path("/tmp"), Path("/var")):
            raise SmokeFailure("unsafe_output_directory")
    resolved = absolute.resolve()
    if resolved in (Path("/"), Path.home().resolve(), REPOSITORY):
        raise SmokeFailure("unsafe_output_directory")
    if resolved.is_relative_to(REPOSITORY) and not any(
        resolved.is_relative_to(REPOSITORY / name) for name in (".artifacts", "out")
    ):
        raise SmokeFailure("unsafe_output_directory")
    if ".git" in resolved.parts or (resolved.exists() and not resolved.is_dir()):
        raise SmokeFailure("unsafe_output_directory")
    return resolved


def synthetic_reference(*, transparent: bool) -> dict[str, str]:
    """Create a deterministic PNG locally, optionally with real alpha."""
    from PIL import Image, ImageDraw

    image = Image.new(
        "RGBA" if transparent else "RGB",
        DIMENSIONS,
        (0, 0, 0, 0) if transparent else (255, 255, 255),
    )
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((256, 256, 768, 768), radius=48, fill=(20, 100, 220, 255))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return {
        "kind": "base64",
        "data": base64.b64encode(stream.getvalue()).decode("ascii"),
        "mime_type": "image/png",
    }


def build_cases(
    settings: Settings,
    *,
    model: str | None = None,
    selected: Sequence[str] | None = None,
    max_cases: int = 5,
) -> list[SmokeCase]:
    """Resolve exact configured families and validate every selected request locally."""
    from ark_mcp.config.model_capabilities import CapabilityRegistry
    from ark_mcp.tools._capability_checks import check_image_request
    from ark_mcp.tools.seedream_generate_image import SeedreamGenerateInput

    names = list(selected) if selected is not None else list(BASE_CASES)
    if (
        not names
        or len(set(names)) != len(names)
        or any(name not in CASE_NAMES for name in names)
        or not 1 <= max_cases <= 5
        or len(names) > max_cases
    ):
        raise SmokeFailure("invalid_case_selection_or_cap")
    registry = CapabilityRegistry()
    try:
        primary = registry.resolve_image_model(model or settings.seedream_default_model)
        if primary.family.value != "seedream_5_5":
            raise SmokeFailure("configured_55_model_required")
    except ValueError:
        raise SmokeFailure("model_not_configured") from None

    opaque_reference = synthetic_reference(transparent=False)
    definitions: dict[str, dict[str, Any]] = {
        "t2i-opaque": {
            "prompt": "A blue ceramic square button centered on a solid white opaque background.",
            "output_format": "jpeg",
        },
        "t2i-transparent": {
            "prompt": "An isolated blue ceramic square button, transparent background, no shadow.",
            "output_format": "png",
            "background": "transparent",
        },
        "reference-edit": {
            "prompt": "Change the blue button to red; preserve its shape and white background.",
            "images": [opaque_reference],
            "output_format": "png",
        },
        "point-edit": {
            "prompt": "Make the selected button green; preserve the rest of the image.",
            "images": [opaque_reference],
            "point": {"x": 500, "y": 500},
            "output_format": "png",
        },
        "bbox-edit": {
            "prompt": "Make the selected button yellow; preserve everything outside the box.",
            "images": [opaque_reference],
            "bbox": {"x1": 250, "y1": 250, "x2": 750, "y2": 750},
            "output_format": "jpeg",
        },
    }
    cases = []
    for name in names:
        request = SeedreamGenerateInput.model_validate(
            {
                "model": primary.model_id,
                "size": "1024x1024",
                "background": "opaque",
                "response_format": "b64_json",
                "persist": True,
                "variations": 1,
                "seed": 42,
                "prompt_optimization": "standard",
                **definitions[name],
            }
        )
        if check_image_request(request, registry.resolve_image_model(request.model)):
            raise SmokeFailure("invalid_case_request")
        cases.append(SmokeCase(name, request))
    return cases


async def run_generation(
    client: Client[Any],
    arguments: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    """Await one direct call with a bounded client deadline and no retry."""
    try:
        result = await asyncio.wait_for(
            client.call_tool(
                "seedream_generate_image",
                {"input": arguments},
                raise_on_error=False,
                timeout=timeout,
            ),
            timeout=timeout,
        )
    except Exception:
        raise SmokeFailure("submission_unknown") from None
    if result.is_error:
        raise SmokeFailure("target_result_error")
    if not isinstance(result.structured_content, dict):
        raise SmokeFailure("missing_structured_result")
    return dict(result.structured_content)


def inspect_image(data: bytes, case: SmokeCase) -> dict[str, Any]:
    """Decode persisted bytes and check format, dimensions, and actual alpha extrema."""
    from PIL import Image

    try:
        expected = "JPEG" if case.request.output_format == "jpeg" else "PNG"
        with Image.open(BytesIO(data)) as image:
            if image.format != expected or image.size != DIMENSIONS:
                raise SmokeFailure("image_format_or_dimensions")
            image.verify()
        with Image.open(BytesIO(data)) as image:
            if image.format is None:
                raise SmokeFailure("invalid_image_bytes")
            image.load()
            alpha_min, alpha_max = image.convert("RGBA").getchannel("A").getextrema()
            if not isinstance(alpha_min, (int, float)) or not isinstance(alpha_max, (int, float)):
                raise SmokeFailure("invalid_alpha_channel")
            transparent = alpha_min < 255
            if case.request.background == "transparent":
                if image.format != "PNG" or not transparent or alpha_max == 0:
                    raise SmokeFailure("missing_visible_alpha")
            elif transparent:
                raise SmokeFailure("unexpected_alpha")
            return {
                "output_format": image.format.lower(),
                "width": image.width,
                "height": image.height,
                "has_transparency": transparent,
                "alpha_min": alpha_min,
                "alpha_max": alpha_max,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    except SmokeFailure:
        raise
    except Exception:
        raise SmokeFailure("invalid_image_bytes") from None


async def verify_output(
    client: Client[Any],
    case: SmokeCase,
    output: dict[str, Any],
    directory: Path,
    *,
    timeout: float,
) -> dict[str, Any]:
    """Read the durable MCP resource, not the provider URL or inline fallback."""
    from ark_mcp.tools.seedream_generate_image import SeedreamGenerateOutput

    try:
        result = SeedreamGenerateOutput.model_validate(output)
        if (
            result.dry_run
            or result.model != case.request.model
            or result.item_errors
            or result.summary is not None
            or len(result.artifacts) != 1
        ):
            raise SmokeFailure("invalid_generation_result")
        artifact = result.artifacts[0]
        canonical_id = str(UUID(artifact.id, version=4))
        if (
            artifact.id != canonical_id
            or artifact.uri != f"seed-media://artifacts/{canonical_id}"
            or artifact.persistence_error is not None
            or artifact.fallback_data is not None
            or artifact.media_type != "image"
            or not artifact.bytes
            or not artifact.sha256
        ):
            raise SmokeFailure("output_not_persisted")
        metadata = [
            image
            for generation in result.generations
            for image in generation.images
            if image.artifact_id == artifact.id
        ]
        if len(metadata) != 1:
            raise SmokeFailure("missing_provider_metadata")
        provider = metadata[0]
        if (
            provider.size is not None
            and re.fullmatch(r"[1-9]\d{0,5}x[1-9]\d{0,5}", provider.size) is None
        ) or provider.output_format not in (None, "png", "jpeg"):
            raise SmokeFailure("invalid_provider_metadata")
        content = await asyncio.wait_for(client.read_resource(artifact.uri), timeout=timeout)
        if len(content) != 1:
            raise SmokeFailure("missing_resource_bytes")
        blob = getattr(content[0], "blob", None)
        if not isinstance(blob, str):
            raise SmokeFailure("missing_resource_bytes")
        data = base64.b64decode(blob, validate=True)
        if (
            not data
            or artifact.bytes != len(data)
            or artifact.sha256 != hashlib.sha256(data).hexdigest()
            or artifact.mime_type != f"image/{case.request.output_format}"
            or content[0].mime_type != artifact.mime_type
        ):
            raise SmokeFailure("persisted_bytes_mismatch")
        observed = inspect_image(data, case)
        filename = f"{case.name}.{case.request.output_format}"
        with (directory / filename).open("xb") as stream:
            stream.write(data)
        return {
            "file": filename,
            "requested": {
                "output_format": case.request.output_format,
                "background": case.request.background,
                "width": DIMENSIONS[0],
                "height": DIMENSIONS[1],
            },
            "observed": observed,
            "provider_metadata": {
                "size": provider.size,
                "output_format": provider.output_format,
                "background": provider.background,
            },
        }
    except SmokeFailure:
        raise
    except TimeoutError:
        raise SmokeFailure("resource_timeout") from None
    except Exception:
        raise SmokeFailure("output_verification_failed") from None


def write_report(directory: Path, report: dict[str, Any]) -> None:
    """Persist only the allowlisted report, replacing it atomically in the private run directory."""
    temporary = directory / "report.tmp"
    with temporary.open("w", encoding="ascii") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(directory / "report.json")


async def run_matrix(
    client: Client[Any],
    cases: list[SmokeCase],
    directory: Path,
    *,
    confirmed_cost: float,
    timeout: float,
) -> int:
    """Price all selected cases first; stop the matrix at the first error without retries."""
    report: dict[str, Any] = {
        "estimated_cost_usd": None,
        "confirmed_estimate_limit_usd": confirmed_cost,
        "price_is_estimate_not_quote": True,
        "cases": [{"case": case.name, "status": "not_run"} for case in cases],
    }
    write_report(directory, report)
    current: dict[str, Any] | None = None
    try:
        estimates = []
        for case, current in zip(cases, report["cases"], strict=True):
            current["status"] = "preflighting"
            preview = await run_generation(
                client,
                case.request.model_dump(mode="json", exclude_none=True) | {"dry_run": True},
                timeout=timeout,
            )
            if preview.get("dry_run") is not True:
                raise SmokeFailure("invalid_dry_run_result")
            amount = (preview.get("preview") or {}).get("estimated_cost_usd")
            if (
                isinstance(amount, bool)
                or not isinstance(amount, (int, float))
                or not math.isfinite(amount)
                or amount < 0
            ):
                raise SmokeFailure("invalid_cost_estimate")
            estimates.append(amount)
            current["status"] = "not_run"
        aggregate = round(math.fsum(estimates), 4)
        report["estimated_cost_usd"] = aggregate
        write_report(directory, report)
        print(
            f"Aggregate estimated price: USD {aggregate:.4f} for {len(cases)} cases "
            "(not a provider quote).",
            flush=True,
        )
        if not math.isfinite(confirmed_cost) or aggregate > confirmed_cost or confirmed_cost <= 0:
            raise SmokeFailure("cost_limit_exceeded")
        for case, current in zip(cases, report["cases"], strict=True):
            current["status"] = "submitting"
            write_report(directory, report)
            output = await run_generation(
                client,
                case.request.model_dump(mode="json", exclude_none=True) | {"dry_run": False},
                timeout=timeout,
            )
            current.update(await verify_output(client, case, output, directory, timeout=timeout))
            current["status"] = "passed"
            write_report(directory, report)
            print(f"{case.name}: passed", flush=True)
        return 0
    except SmokeFailure as exc:
        report["error"] = exc.code
        if current is not None:
            current.update(status="failed", error=exc.code)
        print(f"Stopped: {exc.code}. No automatic resubmission.", file=sys.stderr, flush=True)
        return 1
    except (Exception, asyncio.CancelledError):
        report["error"] = "interrupted_or_unexpected_failure"
        if current is not None:
            current["status"] = "unknown"
        print("Stopped: interrupted_or_unexpected_failure. No resubmission.", file=sys.stderr)
        return 1
    finally:
        write_report(directory, report)


async def execute(args: argparse.Namespace) -> int:
    """Start one local server only after the explicit execution gate has passed."""
    if (
        not args.execute
        or args.confirm_cost is None
        or not math.isfinite(args.confirm_cost)
        or args.confirm_cost <= 0
    ):
        raise SmokeFailure("cost_confirmation_required")

    from fastmcp import Client

    from ark_mcp.config.env import get_settings
    from ark_mcp.server import create_server

    settings = get_settings()
    if not settings.has_modelark or settings.mcp_transport != "stdio":
        raise SmokeFailure("configured_local_modelark_server_required")
    if settings.mcp_auth_mode != "local":
        raise SmokeFailure("local_auth_required")
    directory = safe_output_directory(args.output_dir)
    cases = build_cases(
        settings,
        model=args.model,
        selected=args.selected,
        max_cases=args.max_cases,
    )
    directory.mkdir(parents=True, exist_ok=True)
    run_directory = Path(tempfile.mkdtemp(prefix="seedream55-", dir=directory))
    runtime_settings = settings.model_copy(
        update={
            "artifact_backend": "filesystem",
            "artifact_dir": str(run_directory / "store"),
        }
    )
    async with Client(create_server(runtime_settings)) as client:
        tools = await client.list_tools()
        if not any(tool.name == "seedream_generate_image" for tool in tools):
            raise SmokeFailure("seedream_tool_unavailable")
        result = await run_matrix(
            client,
            cases,
            run_directory,
            confirmed_cost=args.confirm_cost,
            timeout=args.timeout,
        )
    print(f"Report: {run_directory.name}/report.json under --output-dir.")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    if not args.execute:
        arguments.print_help()
        return 0
    for valid, message in (
        (
            args.confirm_cost is not None
            and math.isfinite(args.confirm_cost)
            and args.confirm_cost > 0,
            "--execute requires --confirm-cost with a finite positive USD estimate limit",
        ),
        (1 <= args.max_cases <= 5, "--max-cases must be 1-5"),
        (
            math.isfinite(args.timeout) and 0 < args.timeout <= 1800,
            "--timeout must be 0-1800 seconds",
        ),
    ):
        if not valid:
            arguments.error(message)
    try:
        return asyncio.run(execute(args))
    except SmokeFailure as exc:
        print(f"Stopped: {exc.code}. No automatic resubmission.", file=sys.stderr)
    except KeyboardInterrupt:
        print("Stopped: interrupted. Provider work may already be billed.", file=sys.stderr)
    except Exception:
        print("Stopped: startup_or_execution_failed. Details omitted for safety.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
