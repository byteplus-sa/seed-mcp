# Direct-call output handling

**Local stdio only.** HTTP has no jobs/native tasks/storage/artifact tools or
resources and rejects persistence true. HTTP clients retrieve expiring URLs
themselves; provider calls run directly in the foreground.

Read this when a direct tool call writes local
files, persists provider output, or returns a very large result.

## Local writes

Direct stdio calls use live client MCP roots, falling back to the server's
`OUTPUT_ROOTS` (comma-separated absolute directories).
Without either, explicit `output_path`/`output_dir` writes are rejected
before provider dispatch. `persist_output=true` itself does not need roots.
Inspect `is_error` before `structured_content`, and preserve safe task/request
IDs beside the operation even when an error occurs. Never blindly resubmit.

`seed-health://status` reports the effective Seedream default model/family and
local-export configuration without revealing paths or credentials. A
configured absolute root is not a writable-destination guarantee; request
preflight remains authoritative. The resource makes no provider authorization
or filesystem-readiness probe.

For Seedream, explicit `response_format="b64_json"` requires `persist=true`,
including dry runs. Returned `generations` preserve per-call provenance and
separate advisory byte inspection from delivery, provider metadata and visual
acceptance. Inspection does not regenerate paid images.

## Large results

Prefer local export over returning large artifact bytes into context.
Tools publish their own input/output schemas; no job-discovery call is needed.

The `seedance_create_task` schema is shared by every Seedance model, so it
shows the widest allowed values; take per-model limits from
`ark_list_models(kind='video')` instead (no provider call, small result).

## Provider moderation versus transport failure

An `ambiguous_completion=True` error that names an output audit
(`decision_in_reject_list`, code `55001310`) is a terminal content rejection
with no artifact and no provider task ID to reconcile. Mark the operation
failed and diagnose before any revised submission; never repeat the identical
request.
