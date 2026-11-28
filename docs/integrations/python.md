---
title: Python Client
description: Use FastMCP StdioTransport for safe Seed MCP discovery and an opt-in direct dry run.
---

Use the checkout's locked FastMCP environment, not an independently upgraded
client library. This example uses a real subprocess `StdioTransport` and
ordinary MCP tool calls, with no native task opt-in. It is not a guarantee of compatibility with every future FastMCP
edition.

## Prerequisites and Scope

Complete the [shared launch prerequisites](index.md#prepare-the-launch).
Python has no user/global or project registration file here: the program
explicitly owns one server subprocess. Its checkout and private env file can
live outside the calling project.

Replace `UV`, `CHECKOUT`, and `ENV_FILE` below with actual absolute paths on
the host running Python. The environment dictionary contains only non-secret
paths/settings. The server loads the private `.env` itself; the client does
not read or print it.

Run the program with the prepared checkout's Python environment, for example:

```bash
"/absolute/path/to/uv" --directory "/absolute/path/to/ark-mcp" \
  run --locked --no-sync python "/absolute/path/to/client_example.py"
```

## Discovery and Direct Calls

By default, the program only lists tools and calls `ark_list_models`.
These discovery operations make no provider calls.
It disables optional readiness probes for this
example process. The server still initializes its configured local runtime
state; use an isolated private artifact directory for a standalone preflight
as described in the [integration index](index.md#verify-without-paid-calls).

The explicit `--dry-run` option additionally submits a **non-billable**
Seedream request preview directly. It requires Seedream to be enabled.
The code always sets `dry_run=True`; it has no paid
generation option and never automatically falls back to generation.

```python
import argparse
import asyncio
import os
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

UV = "/absolute/path/to/uv"
CHECKOUT = "/absolute/path/to/ark-mcp"
ENV_FILE = "/absolute/path/to/private/ark-mcp/.env"


async def call(
    client: Client[StdioTransport], name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    response = await client.call_tool(name, arguments, raise_on_error=False)
    if response.is_error or response.structured_content is None:
        raise RuntimeError(f"{name} did not return successful structured output")
    return response.structured_content


async def run_dry_run(client: Client[StdioTransport], names: set[str]) -> None:
    if "seedream_generate_image" not in names:
        raise RuntimeError("Seedream is not enabled; no call was submitted")

    preview = await call(
        client,
        "seedream_generate_image",
        {
            "input": {
                "prompt": "A ceramic mug on a wooden desk.",
                "dry_run": True,
            }
        },
    )
    if preview.get("preview") is None:
        raise RuntimeError("Dry run returned no preview")
    print("Dry run completed; no image was generated.")


async def main(dry_run: bool) -> None:
    with open(os.devnull, "w") as server_stderr:
        transport = StdioTransport(
            command=UV,
            args=[
                "--directory",
                CHECKOUT,
                "run",
                "--locked",
                "--no-sync",
                "python",
                "-m",
                "ark_mcp",
            ],
            env={
                "ARK_MCP_ENV_FILE": ENV_FILE,
                "MCP_TRANSPORT": "stdio",
                "MCP_AUTH_MODE": "local",
                "READINESS_CHECK_PROVIDERS": "false",
            },
            keep_alive=False,
            log_file=server_stderr,
        )
        async with Client(transport, timeout=660) as client:
            tools = await client.list_tools()
            models = await call(client, "ark_list_models", {"input": {}})
            print("Connected; tool count:", len(tools))
            print("Models:", [model["model_id"] for model in models["models"]])
            print(
                "Enabled services:",
                [service["service"] for service in models["services"] if service["enabled"]],
            )
            if dry_run:
                await run_dry_run(client, {tool.name for tool in tools})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args()
    try:
        asyncio.run(main(options.dry_run))
    except Exception:
        raise SystemExit(
            "Connection or tool failed. Inspect private local diagnostics; "
            "do not share credentials or automatically resubmit."
        ) from None
```

The example suppresses server stderr and raw exceptions to avoid accidental
disclosure. For troubleshooting, use owner-only local diagnostics and report
sanitized status/field names, not environment dumps or raw validation errors.
Empty models mean discovery succeeded but the requested providers
may not be configured. Discovery does not verify key validity or entitlement.

## Result and Process Handling

Match the original tool's schema and retain its `input` wrapper. Check
`result.is_error` before using `result.structured_content`. There are no MCP
jobs or native task extensions on either transport.

The client allows 660 seconds for the default 600-second cooperative server
deadline. SDK/SQLite cleanup can exceed it. `keep_alive=False` closes the
subprocess at context exit; finish needed calls before exiting. Do not
automatically retry submission after a timeout or cancellation.

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.

See [Integrations](index.md), [OpenCode](opencode.md),
[Getting Started](../getting-started.md), [Tools](../tools.md), and
[Configuration](../configuration.md).

## Official Sources

- [FastMCP client transports and subprocess lifecycle](https://gofastmcp.com/clients/transports)
- [FastMCP tool calls and structured results](https://gofastmcp.com/clients/tools)

Tool-call/result/error APIs rechecked against the official documentation on
2026-11-17. The direct discovery example is exercised over real subprocess
stdio by `docs/site/scripts/direct-execution.test.mjs`, with isolated state,
no provider credentials and no generation. Exact desktop-client behavior
and paid provider acceptance are not established by this test.
