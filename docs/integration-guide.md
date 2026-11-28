# Integration Guide

This is the technical reference for direct execution. For everyday setup,
start with [Set Up Seed MCP](setup/install.md) and [your client guide](integrations/index.md).
Users can ask their client in plain language; the client handles tool calls.

**Choose the transport first.** Both transports use direct tool calls.
HTTP BYOK exposes 7 tools, plus optional temporary upload preparation, direct foreground provider calls
and anonymous static discovery. It has no jobs/native tasks/local storage/artifact
tools/resources. Keep persistence false and download expiring provider URLs
on the client. See [HTTP setup](setup/shared-server.md).
Anonymous discovery lists configured bindings without environment provider
keys; `services[].enabled` reports registration, not customer entitlement.
Default discovery returns `connection=null`; opt-in HTTP `check_connection`
checks only image/video header presence and exact bindings. Use the
[shared-server preflight](setup/shared-server.md#optional-imagevideo-configuration-check)
and [client snippet generator](setup/shared-server.md#generate-a-client-snippet);
neither verifies authentication, live endpoint lineage or paid provider access.
Explicit per-call `io.modelcontextprotocol/tasks` opt-in is rejected before
provider dispatch, snapshot capture/save or queue creation. Omit the opt-in;
ordinary jobs are unavailable on both transports.

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.

## Prerequisites

Complete guided setup or connect to an existing shared server first.
Developers preparing the server themselves can use
[Manual Installation](setup/manual-install.md).

## Server Overview

The server runs as a `stdio` process — the MCP client spawns it as a
subprocess and communicates over stdin/stdout. The entry point is
`python -m ark_mcp`, which injects `truststore` for macOS TLS
certificate verification before starting the FastMCP server.

Use `python -m ark_mcp` in client configurations so transport security
settings are applied consistently. The server module also injects `truststore`
before provider clients are created.

## Direct Execution

Call the named product tool directly with `{"input": {...}}`. No MCP jobs,
native tasks, worker queue, task snapshots or execution claims exist.

1. Discover configured bindings and services with `ark_list_models`.
2. For Seedream/Seedance, optionally call the product with `dry_run=true`.
3. Make one authorized direct create call and retain safe task/request IDs.
4. Poll Seedance with `gen_task_get`;
   never call create to poll. Respect `recommended_poll_after_ms`.
5. On stdio, explicitly persist successful outputs with the same direct
   poller and `persist_output=true`. HTTP clients download expiring URLs.

Inspect `result.is_error` before using `result.structured_content`;
completion alone is not success. The
[Python client guide](integrations/python.md) has a complete discovery and
direct dry-run example with error checks. The
[first-run guide](setup/first-run.md) provides copyable generation prompts and
optional no-charge checks.

For Seedance, retain every known accepted task/request ID even when an error
is present. A variation can have both `task_id` and `error` after bookkeeping
failure; `submitted` counts known IDs and `failed` counts entries with errors,
so the counters overlap. A single-call failure remains error `ToolResult`
text with IDs rather than structured success output. Never resubmit accepted
work. HTTP polling uses provider-key authorization without local ownership
records. Reconcile uncertain acceptance with the provider using those IDs.
Trusted stdio permits unrecorded IDs, but still
rejects a recorded owner mismatch.

### Deadlines and admission

`MCP_ADMISSION_TIMEOUT_SECONDS=2.0` (finite positive, max 30) bounds all waiting
for owner then provider slots. Owner-first acquisition prevents a same-owner
backlog occupying provider slots. Budget is reserved after admission.
`ADMISSION_TIMEOUT` means this attempt did not dispatch; other variations may
have done so. No automatic retry loop is added.

`MCP_TOOL_TIMEOUT_SECONDS=600.0` (finite positive, max 3600) starts at wrapper
entry after MCP parsing, before credentials and admission.
Use client timeout **660 seconds** and compatible proxy settings.
SQLite/SDK cleanup may exceed this cooperative deadline.
`TOOL_DEADLINE_EXCEEDED` is a text-only error preserving mutation uncertainty
and known safe accepted IDs. External cancellation propagates; timeout does
not cancel accepted provider work. Never blindly resubmit. Read-only polling
and discovery avoid saturated generation slots, but HTTP global limits still
apply. See [Direct Execution](../specs/SPEC_DIRECT_EXECUTION.md).

## Seedream Review And Edit

Generation delivery and visual acceptance are separate outcomes. This workflow
uses existing tools; the Seed MCP integration exposes no native OCR or layer
decomposition, even when the provider API supports those operations.

1. Discover the model and dry-run the intended request. Record an explicit
   paid-attempt limit and USD estimate budget covering generation and edits.
   `preview.price_source` is `builtin`,
   not an account-specific quote or actual charge. Stop when either limit is reached.
2. Submit once, directly on either transport. Keep completed
   per-call `request_id`, submitted `seed`, final `prompt_sha256`,
   `request_options`, usage, artifact ID and artifact SHA-256. Store the original
   prompt and reference hashes in a private manifest; the hash is not the prompt.
3. Check `item_errors` or variation errors, persistence and byte `inspection`.
   A delivered PNG is not automatically a passing image. Inspection problems
   do not cause paid rerolls.
4. Review the immutable output visually with an authorized human or a separately
   configured review system outside this server. Use its provider URL;
   local stdio can also export/read or upload a durable image. Evaluate
   exact spelling/case, forbidden text (including absence checks), object/person
   counts, geometry, visibility, anatomy and composition against the brief.
   Automated review is fallible evidence, not authoritative OCR.
5. Record `Pass`, `Partial`, `Fail`, or `Not evaluated` with evidence. A reviewer
   refusal or unavailable review is `Not evaluated`, not a generation failure;
   exclude it from assessed pass-rate denominators and do not bypass refusals.
6. For an authorized correction, call `seedream_generate_image` with the source
   in `images`, a focused edit instruction and optional structured `point`/`bbox`.
   Preserve the original; record parent artifact/hash, edit instruction, submitted
   markup hash, new request/artifact IDs and review as a new paid attempt.
   A fixed seed helps reproduce request settings but does not guarantee identical
   pixels or successful text/count/geometry.
7. Select an output only after acceptance. Verify inline image previews after
   publishing to a sheet or document; publishing/link repair belongs to the
   consumer integration, not the Seedream adapter.

Never resubmit after an ambiguous timeout simply to get another answer. Resume
polling of known provider tasks or reconcile its request ID first. Recovery of persisted media
is distinct from another paid generation.

### Opt-In Seedream Smoke Matrix

`uv run python scripts/smoke_seedream55.py` prints offline help and makes no
provider calls. Live execution requires both `--execute` and
`--confirm-cost <positive USD estimate limit>`, configured local ModelArk
credentials and an exact configured 5.5 model (use `--model` if Pro is the default).
The script dry-runs every selected case and prints the aggregate estimate before
submitting any billable generation. A rejected/ambiguous call stops the matrix;
submissions are never retried.

Default cases cover opaque JPEG, transparent PNG, reference edit, point edit and
bbox edit, using synthetic local PNG references rather than paid setup images.
`--case` selects a subset; `--max-cases` caps the count. Optional Pro compatibility
requires an explicit `--pro-model` and sufficient case cap (`--max-cases 6` for
the complete matrix). Results go to a fresh private run directory under
`.artifacts` by default, with sanitized `report.json` and durable media.

The script checks persistence, hashes, decode, dimensions, format and visible
alpha. A byte-smoke pass does not prove the requested color change or region
adherence: visually review editing semantics and composition separately. Polling
is bounded; a timeout is not permission to rerun accepted work.

## Python Task Workflow

This optional developer example is not needed for setup. Run it in the
reviewed environment with `ARK_MCP_ENV_FILE` pointing to your private file
and `SMOKE_REFERENCE_IMAGE_URL` pointing to an accessible reference
image. **This example submits one billable video generation.** The provider ID
is saved before polling; if polling fails, use that ID to resume retrieval rather
than repeating submission. The provider ID identifies the video generation;
there is no MCP job ID.

<details>
<summary>Direct-call Python example (billable)</summary>

```python
import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

async def main():
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "ark_mcp"],
        env={
            "ARK_MCP_ENV_FILE": os.environ["ARK_MCP_ENV_FILE"],
            "MCP_TRANSPORT": "stdio",
            "MCP_AUTH_MODE": "local",
        },
        keep_alive=False,
    )
    async with Client(transport, timeout=660) as client:
        created = await client.call_tool(
            "seedance_create_task",
            {
                "input": {
                    "prompt": "A gentle camera move through the scene",
                    "images": [
                        {
                            "kind": "url",
                            "url": os.environ["SMOKE_REFERENCE_IMAGE_URL"],
                            "role": "reference_image",
                        }
                    ],
                    "duration": 5,
                    "resolution": "480p",
                }
            },
            raise_on_error=False,
        )
        if created.is_error or created.structured_content is None:
            raise RuntimeError("Create failed; reconcile safe IDs without resubmission")
        provider_id = created.structured_content["tasks"][0]["task_id"]
        directory = Path(".artifacts")
        directory.mkdir(exist_ok=True)
        with (directory / "provider_tasks.jsonl").open("a") as stream:
            stream.write(json.dumps({"task_id": provider_id}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

        for _ in range(30):
            status = await client.call_tool(
                "gen_task_get",
                {"input": {"task_ids": [provider_id], "persist_output": False}},
                raise_on_error=False,
            )
            if status.is_error or status.structured_content is None:
                raise RuntimeError(f"Resume polling provider task {provider_id}")
            result = status.structured_content
            if result["errors"]:
                raise RuntimeError(f"Provider task {provider_id}: {result['errors'][0]}")
            state = result["tasks"][0]["status"]
            if state == "succeeded":
                break
            if state in {"failed", "cancelled", "expired"}:
                raise RuntimeError(f"Provider task {provider_id}: {state}")
            await asyncio.sleep(result["recommended_poll_after_ms"] / 1000)
        else:
            raise TimeoutError(f"Resume polling provider task {provider_id}")

        completed = await client.call_tool(
            "gen_task_get",
            {"input": {"task_ids": [provider_id], "persist_output": True}},
            raise_on_error=False,
        )
        if completed.is_error or completed.structured_content is None:
            raise RuntimeError("Persistence failed; retain the provider ID")
        print(completed.structured_content["tasks"][0]["outputs"])

asyncio.run(main())
```

`client.call_tool()` awaits the ordinary result. No task extension or second
client is needed; do not launch concurrent processes against the same SQLite state.
A provider success can still have `video=null` when best-effort persistence
fails; inspect the result before treating the artifact as delivered. The same
submit/status/persistence sequence is tested offline by the smoke-workflow tests;
`tests/e2e/test_stdio_tasks.py` separately verifies a real subprocess task result.

</details>

## Providing Credentials

For stdio use a private file outside the repository, referenced by `ARK_MCP_ENV_FILE`.
Enter keys locally, never in chat, client JSON or shared configuration.
[Guided setup](setup/install.md) prepares that file; [Provider Keys](api-keys.md)
explains which fields you need. Inherited environment variables can override
the file, so investigate shadowing without displaying values.

## Claude Desktop

Use the [Claude Desktop guide](integrations/claude-desktop.md). A separate
coding agent can prepare local setup; Desktop then starts Seed MCP automatically.

## Cursor IDE

Use the [Cursor guide](integrations/cursor.md). Prefer guided setup and check
actual discovery results, not just a connection indicator.

## VS Code (MCP Extension)

Use the [VS Code guide](integrations/vscode.md). It distinguishes the
profile/workspace `servers` format from portable Copilot configuration.

## MCP Inspector

The MCP Inspector is an optional developer tool, not a setup requirement.
The ordinary [connection check](integrations/index.md#verify-without-paid-calls)
runs inside your AI client.

<details>
<summary>Developer Inspector launch</summary>

From an already prepared checkout, with the private env-file path configured:

```bash
make inspect
```

This launches `fastmcp inspect src/ark_mcp/server.py:mcp`; the server
module injects `truststore` before provider clients are created.

For HTTP inspection, use an existing protected server and your authorized
connection credentials. Never export provider keys into shell history or
disable authentication to connect.

</details>

## Troubleshooting

### SSL Certificate Errors (macOS)

If you see `CERTIFICATE_VERIFY_FAILED`, confirm `truststore` is installed and
start through `python -m ark_mcp` so the complete entrypoint runs.

### "API key not configured" Error

Check the private `ARK_MCP_ENV_FILE` path, requested credential names and
feature flags, then reconnect after finishing active calls. Do not print the
file or raw settings-validation exceptions. See
[missing tools](troubleshooting.md#missing-provider-tools).

### Server Not Discovered by Client

Have the setup agent check the resolved executable, checkout, locked
environment and any unfinished UI approvals. It should inspect private
diagnostics locally, not dump complete logs into chat. See
[Manual Installation](setup/manual-install.md#verify-without-spending).

### Tools Missing

On local stdio, if only some products' tools are registered:

- No ModelArk key → no `seedream_generate_image`, `seedance_create_task`,
  `gen_task_*`
- Seed Audio and object storage need their own credentials
  or feature flags; see
  [Configuration](configuration.md).

`ark_list_models` reports which optional services are enabled. HTTP registers
provider tools without operator keys; invocation
still requires the selected live provider key and client secret.

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `BYTEPLUS_MODELARK_API_KEY` | For image/video | — | ModelArk Bearer auth key |
| `BYTEPLUS_SEED_SPEECH_API_KEY` | For audio | — | Seed Speech X-Api-Key |
| `BYTEPLUS_MODELARK_BASE_URL` | No | `https://ark.ap-southeast.bytepluses.com/api/v3` | ModelArk region endpoint |
| `BYTEPLUS_SEED_AUDIO_BASE_URL` | No | `https://voice.ap-southeast-1.bytepluses.com` | Seed Speech endpoint |
| `SEEDREAM_DEFAULT_MODEL` | No | `dola-seedream-5-5-261028` | Seedream 5.5 model ID; retain an explicit 5.0 Pro default if not authorized |
| `SEEDANCE_DEFAULT_MODEL` | No | `dreamina-seedance-2-5-260628` | Default Seedance model ID for `seedance_create_task` (Seedance 2.5) |
| `MCP_TRANSPORT` | No | `stdio` | `stdio` or `http` |
| `MCP_HOST` | No | `127.0.0.1` | HTTP bind address |
| `MCP_PORT` | No | `3000` | HTTP port |
| `MCP_AUTH_MODE` | No | `byok` | Required mode for HTTP; explicit `local` is stdio-only |
| `MCP_IDENTITY_HMAC_KEY` | HTTP operator | empty | 64 lowercase hex from 32 random bytes; not a customer credential |
| `MCP_IDENTITY_KEY_VERSION` | No | `1` | Positive identity namespace version |
| `MCP_ALLOWED_HOSTS` | For HTTP | loopback | Accepted Host headers |
| `MCP_ALLOWED_ORIGINS` | For browser HTTP | — | Accepted browser origins |
| `ARTIFACT_DIR` | No | `.artifacts` | Local artifact storage |
| `ARTIFACT_TTL_SECONDS` | No | `604800` (7 days) | Artifact retention |

HTTP clients send only the selected `X-ModelArk-Api-Key` or
`X-Seed-Speech-Api-Key`, plus required
`X-MCP-Client-Secret` (client-generated 32 random bytes as 64 lowercase hex).
Discovery is anonymous/static; provider calls including dry runs need headers.
Keys are not persisted and there is no environment fallback, OAuth, signup or
server-issued key. HTTP has no database or client-level task ledger; provider keys
authorize task access. Local stdio retains SQLite. Preserve old state and accepted
IDs during a separately reviewed transition. See [Self-Hosting](self-hosting.md).

See [Configuration](configuration.md) for model bindings, body limits,
concurrency, and budget settings.
