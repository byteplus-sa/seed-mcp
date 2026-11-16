# Troubleshooting

Start with the symptom you see. You usually do not need to reinstall Ark or
run server commands manually.

| Symptom | First thing to try |
| --- | --- |
| Ark is not listed in your client | Review the client-specific MCP setup and unfinished approval steps |
| Connected, but tools are missing | Reconnect after finishing active jobs; check requested services and private-file configuration |
| A request is still working | Ask the client to poll the existing job/task, not submit it again |
| An HTTP server rejects a provider call | Check private selected-provider and client-secret headers; discovery is anonymous, not proof of key validity |
| You need help diagnosing local setup | Ask your setup agent to inspect paths and settings metadata without printing secrets |

Use the [discovery-only check](integrations/index.md#verify-without-paid-calls)
before any paid test. Never share populated credential files, full client
configuration, raw environment dumps or unredacted logs in chat.

## SSL Certificate Errors

Ark already includes and enables `truststore`. If you see
`CERTIFICATE_VERIFY_FAILED`, ask your setup agent to check that the client
uses the documented `python -m ark_mcp` launch and the reviewed locked
environment. Have your IT administrator check any corporate proxy or system
certificate configuration. Do not disable TLS verification or independently
add/upgrade dependencies to fix this.

## "API key not configured" Error

If a tool raises `BYTEPLUS_*_API_KEY is not configured`, the server did not
find the credential in the environment. Check:

1. The client points `ARK_MCP_ENV_FILE` to the intended private file
2. The key name matches exactly (`BYTEPLUS_MODELARK_API_KEY` or
   `BYTEPLUS_SEED_SPEECH_API_KEY`)
3. No leading/trailing whitespace in the value
4. The client was reconnected after saving the file, without interrupting active jobs

When a credential is absent, the server skips registering that product's
tools — it does not register a broken tool.

## `ark_job_capabilities` Returns No Targets

An empty `targets` list means your connection has no visible background
targets. Locally, provider credentials or feature flags may be missing;
on a shared server, fixed team scopes also exclude administrative tools.

1. **Finish active jobs, then reconnect `ark-seed` in the client you are using.**
   Configuration is read at startup. Another editor's running server does not
   prove this client's connection is current.
2. **Ask your setup agent to check the private-file path and permissions.**
   `ARK_MCP_ENV_FILE` must be an absolute path on the actual execution host.
   Do not move keys into client JSON as a workaround.
3. **Check only the product you need.** Some tools need both a credential and
   a feature flag. Use [Provider Keys](api-keys.md) and [Configuration](configuration.md).
4. **Check inherited settings or shared-server permissions.** An environment
   value can override the private file. Inspect names/presence without printing
   values; for shared deployments, ask the operator to check enabled products
   and the fixed team permissions.

Then repeat discovery. A startup warning about missing credentials is useful
evidence, but absence of a warning is not proof that the right file was loaded.

## Model Not Found / Not Activated

If the provider returns `403 FORBIDDEN` with "model not activated":

1. Check the model ID in `.env` matches your console
2. Confirm the model is activated in your BytePlus region
3. Verify the base URL matches your key's region

Model IDs and access depend on your account and region. Ask your setup agent
or administrator to compare discovery with the provider console before making
another billable call. A local configuration check does not prove activation.

## Provider URL Expired

Provider output URLs expire:

- **Seed Audio**: 2 hours
- **Seedream**: 24 hours
- **Seedance**: 24 hours (video and last-frame)

Persistence defaults to false. On stdio, explicitly request `persist=true`
or `persist_output=true` for durable resources (default artifact TTL 7 days).
HTTP rejects true and has no artifact tools/resources; clients must download
provider URLs before expiry.

If you set `persist=False`, the tool returns the raw provider URL which
will expire. Use the artifact resource instead.

### Artifact has `persistence_error`

An `ArtifactRef` with `persistence_error` means the output was generated and
billed but could not be stored durably (after download retries). The call
still succeeded; nothing was lost yet:

- `id="provider-url"`: `uri` is the temporary provider URL, valid until
  `persistence_error.source_url_expires_at`. Call `seed_media_persist_url`
  with that `uri`, `media_type`, `mime_type`, and `source_expires_at` before
  it expires.
- `id="inline-fallback"`: the bytes are in `fallback_data` (Base64). Save them
  directly; they are not stored anywhere else.

Check `persistence_error.code` and `retryable`: `output_too_large` and
`untrusted_output_host` will not succeed on retry; `download_failed` and
`storage_failed` usually will. For persistent download timeouts, raise
`ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS` or `ARTIFACT_DOWNLOAD_MAX_ATTEMPTS`.

Seedance instead reports `outputs[].persistence_issue` with
`outputs[].persistence="failed"`; OmniHuman uses top-level `persistence_issue`
and `persistence="failed"`. Keep `source_url` and retry persistence through a
background poll or `seed_media_persist_url` before expiry. An artifact need not
exist on failure.

### `output_path` rejected or `export_error` set

- `... is disabled: no output roots are configured`: the client does not
  advertise MCP roots and `OUTPUT_ROOTS` is empty (a call inside
  `ark_job_submit` never has MCP roots). Set `OUTPUT_ROOTS` to one or more
  absolute directories.
- `must be inside an allowed output root` / `must be an absolute path`: use an
  absolute path under a client root or an `OUTPUT_ROOTS` entry.
- `only supported in stdio transport mode`: local paths are stdio-only.
- `requires persist=true` / `requires persist_output=true`: local copies are
  written from the durable artifact.
- `already exists with different content`: pass `overwrite=true`.

Path errors are raised before the provider is called. A failed write after
generation is reported in `ArtifactRef.export_error` instead; the durable
artifact is unaffected and can be exported later with
`seed_media_export_artifact`.

## Seedance Task States

| Status | Meaning |
|---|---|
| `queued` | Task is waiting to start |
| `running` | Task is generating |
| `succeeded` | Task completed, video available |
| `failed` | Task failed, check `error` field |
| `expired` | Task expired before completion |
| `cancelled` | Task was cancelled via DELETE |

### Why is there no queue position or ETA?

ModelArk publishes no queue position or ETA for Seedance tasks. The `queue`
field on each video task returned by `gen_task_get` is derived by the server from the task's own timestamps: time queued, time
running, service tier (`flex` usually queues longer), and `expires_at`, the
time the provider fails an unfinished task (`created_at` +
`execution_expires_after`; `expires_at_estimated=true` means the 48-hour
default was assumed). Relay `queue.hint` to the user, and pass every task ID
to one `gen_task_get` call until `all_terminal` is `true`.

### Cannot Cancel or Delete

- `running` tasks cannot be cancelled or deleted — wait for completion
- `cancelled` tasks cannot be deleted

The `gen_task_cancel_or_delete` tool (Seedance tasks) requires `expected_status` to
match the actual status, preventing accidental destructive actions.

## Timeout on Long Generations

Seedream Pro and long Seed Audio generation can take 1-5 minutes. The
default request timeout is 10 minutes (`BYTEPLUS_REQUEST_TIMEOUT_MS=600000`).

If you experience timeouts:

1. Increase `BYTEPLUS_REQUEST_TIMEOUT_MS` (or `SEED_UNDERSTANDING_TIMEOUT_MS`
   for `seed_understand` and `seed_audio_understand` only)
2. Check your network connectivity to the BytePlus region
3. Check `retryable` and `ambiguous_completion` on the `TIMEOUT` error. What a
   timeout means depends on the call:

| Call | `retryable` | `ambiguous_completion` | Server retries? | What to do |
|---|---|---|---|---|
| Create / generate / cancel / delete | `false` | `true` | No | It may have succeeded upstream. Do not retry blindly; reconcile by task ID or request ID |
| Task polls (Seedance, OmniHuman) | `true` | `false` | Yes | Safe to poll again |
| `seed_understand` / `seed_audio_understand` chat completion | `false` | `true` | No | Completion may already be billed. Reconcile by request ID when available; do not blindly repeat it |
| Variation batch deadline | see `error.phase` | | No | `queued` (`QUEUE_TIMEOUT`) is safe to retry; `generating` is ambiguous |

This table describes timeouts after possible dispatch. Uncertain
read/write/protocol failures and malformed provider 2xx responses are also
ambiguous/nonretryable for mutations and understanding completions.
Chat/mutation 5xx responses are ambiguous and never automatically retried,
even when marked `retryable=true`. Eligible 429 rejections and demonstrably
pre-dispatch failures can be retried, but understanding disables all `TIMEOUT`
retries, including connect/pool timeouts. See the
[retry policy](runtime.md#retry-policy-providersretrypy); do not add blind
client retries.

Seedance may return a known `task_id` alongside a bookkeeping error. Keep it:
`submitted` counts known IDs, while `failed` counts entries with errors, so
those counts can overlap. Single-call failures keep IDs in error `ToolResult`
text. Never recreate accepted work. HTTP polling needs recorded ownership;
if ownership recording failed, reconcile with the provider using task/request IDs.
Trusted stdio permits unrecorded IDs, but still rejects recorded owner mismatches.

Budget reservations are committed for every `TIMEOUT`, since a timed-out
call may still have been billed.

## `seed_understand` Result Too Large or Missing Reasoning

The reasoning trace is no longer returned: deep thinking is always on, but
`choices[].reasoning_content` was removed and `thinking` is ignored. Only the
final answer comes back; `usage.reasoning_tokens` reports thinking cost. If
the answer itself is too large for the client context:

- Set `save_to` to an absolute path (stdio, inside an output root) and
  `return_content="none"` or `"summary"` (first 2,000 characters). The full
  answer is written to disk; `saved_path` and `content_chars` tell you where
  and how long.
- With a JSON `response_format`, `choices[].parsed` is returned even when
  `return_content` is `none`.
- If the answer ends with `finish_reason="length"`, raise `max_tokens`
  (it includes thinking tokens). `json_retry` does not retry truncated
  answers.

## Client Timeouts vs Provider Latency

A client-side MCP timeout is distinct from a server failure. Seedream Pro and
Seedance provider submissions can take 60–150 s (longer under cold start or
provider queue). Local stdio requires background execution for those operations.
HTTP uses direct foreground calls: increase client/proxy timeouts, keep
persistence false and reconcile lost responses without automatic resubmission.
The workflow below is stdio-only.

- Submit `seedance_create_task`, `seedream_generate_image`, and
  `seed_audio_generate` through the `ark_job_*` workflow below. Its terminal
  result contains the typed tool output.
- On a task-capable client, you may instead invoke those tools with MCP task
  metadata, retain the returned MCP task ID, and poll `tasks/get` at the
  advertised interval until terminal.
- For video generation, the background result contains the provider
  task ID. Poll `gen_task_get` (Seedance) or `omnihuman_get_task` (OmniHuman)
  in the foreground with `persist_output=false` (explicitly set this for
  OmniHuman). Then run the poller once through `ark_job_submit`
  with `persist_output=true` to keep the outputs. Never resubmit the create
  tool to poll.
- If a client disconnects after task acceptance, reconcile with the returned
  MCP task ID or provider task ID rather than resubmitting (see
  `ambiguous_completion`).

### Client rejects task-augmented execution

If Codex, Cursor, or another MCP client reports that the server requires
task-augmented execution but its transport does not support it, do not call the
required-task provider tool directly and do not switch it to foreground mode.

1. Call `ark_job_capabilities` and confirm the target is listed.
2. Call `ark_job_submit` with the target tool name and its original arguments.
3. Retain the returned Ark `job_id` and poll `ark_job_get` at
   `poll_after_ms` until terminal.
4. Read the original tool output from `result.structured_content`.

This remains a real background task on the same worker. For a Seedance or OmniHuman submission, the provider task ID appears inside the completed original
result and must be retained separately. A missing target usually means its
local provider credential or feature flag is unavailable. This workflow is
stdio-only; HTTP calls providers directly and has no background targets.

### Background job is not available

`Background job is not available in this server instance` means the local
stdio process cannot resolve the job ID:

- The job was submitted by a **different** `ark-mcp` process. Each `stdio`
  client starts its own process; poll through the original process.
- The server restarted: the default in-memory Docket backend discards active and
  retained jobs. Redis retention is the durability path.
- The job ID is wrong, or its retained result expired.

HTTP has no job tools/native tasks. Do not try to share stdio jobs through an
HTTP endpoint. Provider IDs already returned by a job are separate and can be
used to reconcile provider outcomes under the original authorized scope.

## Artifacts Not Persisting

Check:

1. `ARTIFACT_DIR` is writable
2. Disk has sufficient space
3. `ARTIFACT_BACKEND` is `filesystem`, or `object_storage` with working
   TOS/S3 credentials

A storage failure no longer fails the tool call; look for
`persistence_error` on the returned artifact (see above).

Run `make check-env` to validate configuration.

## HTTP Server Refuses to Start

All HTTP binds require `MCP_AUTH_MODE=byok` (default), operator
`MCP_IDENTITY_HMAC_KEY` (32 random bytes as 64 lowercase hex) and positive
identity version (default `1`). Check positive rate/body/in-flight/state limits,
fixed official origins and fresh SQLite state. Explicit local auth is
stdio-only. No compatibility migration exists. Do not delete older state to
work around startup failure. See [self-hosting](self-hosting.md).

## HTTP Authentication Fails

Configure only the selected provider key header and `X-MCP-Client-Secret`,
including dry runs. The client secret is 32 random bytes as 64 lowercase hex.
Duplicate, empty or malformed values fail; `Authorization` is rejected.
There is no OAuth, signup or server-issued key. Discovery is anonymous/static
and does not validate provider keys. Never print secrets while troubleshooting.
Changing provider/client/HMAC credentials changes ownership scope with no
recovery bridge; use the original authorized scope for older tasks.

## Unknown Tool over HTTP

Check `ark_list_models.services`. HTTP has 9 tools, or 12 when OmniHuman is
enabled, and no jobs/native tasks/storage/artifact tools/resources. Missing
operator provider keys do not hide HTTP tools. Asset administration is
unavailable on either transport. Call HTTP provider tools directly in the
foreground; configure timeouts rather than resubmitting uncertain work.

## Running Tests

```bash
make test          # run all tests
make lint          # ruff check
make typecheck     # mypy
```

Tests use `respx` and an autouse socket guard—real network calls fail the suite.
