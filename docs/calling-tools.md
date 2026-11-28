---
title: Calling Tools
description: MCP call envelopes, results, video polling and safe recovery.
---

Most users can [create media with a prompt](setup/first-run.md).
This page is for custom clients and integrations.

## Direct Execution

Configure [private HTTP headers](setup/install.md) separately, then call the
tool by name with an `input` wrapper. For example, this previews an image
request without generating or billing:

```json
{
  "name": "seedream_generate_image",
  "arguments": {
    "input": {
      "prompt": "A red ceramic cup on a wooden table",
      "dry_run": true
    }
  }
}
```

Use the [tool reference](capabilities.md) for exact fields and model limits.
Do not request `io.modelcontextprotocol/tasks`: calls run directly, without
MCP jobs or native tasks. Hosted persistence must remain false.

## Results

Check the MCP `isError` flag before using `structuredContent`. In the
[FastMCP Python client](https://gofastmcp.com/clients/tools), the corresponding
properties are `is_error` and `structured_content`; use `raise_on_error=False`
to inspect error results yourself.

Errors can be text-only. Keep any accepted task/request IDs and check
per-item errors in variation batches. A completed call is not proof that
every item succeeded.

## Video Polling

1. Call `seedance_create_task` once and save every accepted `task_id`.
2. Call `gen_task_get` with those IDs and `persist_output=false`.
3. Follow `recommended_poll_after_ms` until the tasks are terminal.
4. Download successful outputs before their URLs expire.

Task access follows the supplied provider key. There is no client-secret
ownership ledger or durable replay.

## Timeouts and Retries

Use a 660-second client timeout for the default 600-second cooperative
deadline. A timeout does not cancel provider work.

- `ADMISSION_TIMEOUT`: this attempt did not dispatch; other batch items may have.
- `TOOL_DEADLINE_EXCEEDED` or a lost response: retain accepted IDs and reconcile.
- Queued or running video: poll the existing ID, not the create tool.

Omit `idempotency_key`; legacy keys are rejected. Never blindly retry an
uncertain create, cancel or delete. It may already have succeeded or been billed.

## Seedream Review and Edit

Review delivered images visually. For an approved correction, send the source
URL in `images` with a focused edit instruction and optional `point` or `bbox`.
Keep the original and set a paid-attempt limit; delivery is not visual acceptance.
There is no native OCR or layer-decomposition tool.

Detailed contracts: [direct execution](../specs/SPEC_DIRECT_EXECUTION.md) and
[HTTP submission safety](../specs/SPEC_HOSTED_BYOK.md#http-submission-safety).
