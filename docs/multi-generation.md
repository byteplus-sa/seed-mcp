# Multi-Generation

The server supports two mechanisms for producing multiple outputs from one
tool call: **native provider batch** (one API call, many outputs) and
**client-side parallel variation** (many independent API calls with bounded
concurrency). Both transports await ordinary direct calls and return the
original typed tool result. Neither exposes MCP jobs or native tasks.

HTTP uses direct foreground calls and returns that tool result directly.
It has no jobs/native tasks/storage/artifact tools/resources. HTTP persistence
must be false; local explicit true remains supported, with false the global
default. Download HTTP provider URLs yourself before expiry.

## Native provider batch

Seedream supports generating multiple images in a single provider API call
via the `max_images` parameter. This is a native capability of the BytePlus
API and is only supported by **Lite** and **4.x** model families.

**How it works:**

1. The client passes `max_images` (1-15) on `seedream_generate_image`.
2. The handler validates it against the capability registry:
   - Lite and 4.x allow batch; Pro rejects `max_images > 1`.
3. The provider adapter translates `max_images` into
   `sequential_image_generation: "auto"` with
   `sequential_image_generation_options: {"max_images": N}`.
4. The provider returns images in one response. Each is returned as a
   provider-URL reference, or explicitly persisted as a local artifact.

This is a **single `POST /images/generations` call** — one request, one
response, multiple outputs. It is the most efficient path and should be
preferred over variations when the model supports it.

| Model family | Supports `max_images` | Max images |
|---|---|---|
| **Pro** (`seedream_pro`) | No | 1 |
| **5.5** (`seedream_5_5`, default) | No | 1 |
| **Lite** (`seedream_lite`) | Yes | 15 |
| **4.x** (`seedream_4x`) | Yes | 15 |

## Client-side parallel variations

When a product does not support native batch (or when the client needs
per-variation control like distinct prompts or seeds), the `variations`
field on the generation tools makes multiple independent API calls in
parallel. There are no separate `*_variations` tools; every variation shares
the call's other inputs, including reference media.

### Products with variation support

| Tool | Product | Uses native batch? | Parallel mechanism |
|---|---|---|---|
| `seedream_generate_image` with `variations` 2-10 | Seedream (any model; cannot be combined with `max_images > 1`) | No (always parallel calls) | `run_variation_batch` |
| `seed_audio_generate` with `variations` 2-5 | Seed Audio | No | `run_variation_batch` |
| `seedance_create_task` with `variations` 2-5 | Seedance (every configured model) | No | `run_variation_batch` |

### How it works

The shared helper [`run_variation_batch`] in `tools/_parallel.py`:

1. For Seedream, derives one seed per variation from the request's `seed`
   (the base seed) via `generate_seeds`:
   - `seed` omitted → provider randomizes each (seed not recorded).
   - `seed=-1` → client picks random seeds (recorded for reproducibility).
   - `seed=N` → deterministic sequence `[N, N+1, N+2, ...]` modulo
     `2147483648`.

   Seed Audio and Seedance take no seed; their variations differ by sampling
   or by `variation_prompts`.
2. Resolves prompts via `resolve_prompts`: either per-variation prompts or
   the same base prompt repeated N times.
3. Launches N tasks, each calling the provider API independently.
4. Bounds concurrency with an `asyncio.Semaphore` (default from
   `DEFAULT_MAX_CONCURRENT` in `tools/_cost.py`).
5. Waits for all of them under one batch deadline (see below), then builds a
   `VariationSummary` with per-variation success/failure tracking.

Seedream also returns `generations`, ordered by zero-based `variation_index`,
for completed provider calls. Each includes per-call usage, echoed safety ID,
and provider-reported image size, format and actual background, with matching
artifact IDs. Failed provider calls have no metadata entry; absent provider
values remain `null`. The top-level `usage` remains single-call-only.

### Deadlines and failure phases

Individual variations have no separate wall-clock timer, but the direct
call's cooperative deadline covers all phases, including slot waiting.
`MCP_TOOL_TIMEOUT_SECONDS=600.0` (finite positive, max 3600) starts at wrapper
entry. Provider admission separately bounds owner-first/provider waiting to
`MCP_ADMISSION_TIMEOUT_SECONDS=2.0` (finite positive, max 30), before budget
reservation. `ADMISSION_TIMEOUT` means only this attempt did not dispatch;
other variations may already be accepted.

Whole-call expiry returns text-only `TOOL_DEADLINE_EXCEEDED`, with mutation
uncertainty and known safe accepted IDs, rather than a guaranteed complete
variation summary. Use client timeout 660 seconds. SDK/SQLite cleanup can
exceed the deadline; neither it nor client cancellation cancels provider work.
Never blindly resubmit a partial batch. HTTP one-key-per-batch journal recovery
replays only complete saved success; unresolved attempts never resume.

One batch deadline is a safety net for a stuck batch:

```text
waves          = ceil(variations / max_concurrent)
per_variation  = request_timeout × 3
               + download_timeout × download_attempts   (persisting tools only)
batch_deadline = waves × per_variation
```

`request_timeout` is `BYTEPLUS_REQUEST_TIMEOUT_MS`; `download_timeout` and
`download_attempts` are `ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS` and
`ARTIFACT_DOWNLOAD_MAX_ATTEMPTS`. Seedance variations only submit tasks,
so their deadline omits the download term.

A variation that hits the batch deadline, or whose output could not be
stored, records where it stopped in `error.phase` (ordinary provider errors
leave `phase` null and keep their provider `code`, `retryable`, and
`ambiguous_completion`):

| `phase` | Meaning | Typical code | Retry? |
|---|---|---|---|
| `queued` | Never started before the batch deadline | `QUEUE_TIMEOUT` (`retryable=true`) | Safe to retry |
| `generating` | Provider call in flight at the deadline | `TIMEOUT` (`ambiguous_completion=true`) | Do not retry blindly; the provider may have completed it |
| `persisting` | Output generated, storing it failed | upper-cased persistence code (e.g. `STORAGE_FAILED`) | Output was billed; see below |

Most storage failures do not produce an error at all: a variation whose
output has a provider URL comes back as a success with an unpersisted
`ArtifactRef` (`id="provider-url"`, `persistence_error` set), and inline
Base64 comes back as `id="inline-fallback"` with `fallback_data`. The
`persisting` error appears only when neither fallback is possible (for
example inline output above `ARTIFACT_INLINE_FALLBACK_MAX_BYTES`). If the
deadline hits while a variation is persisting and its output URL is already
known, the variation returns that unpersisted output instead of an error. Recover it with `seed_media_persist_url`. A persistence failure never
drops a billed output; see [Artifacts](artifacts.md#persistence-failures).

### Writing variations to a local directory

On stdio transport, `seedream_generate_image` and `seed_audio_generate`
accept `output_path` (plus `overwrite`); with `variations > 1` it must be a
directory ending in `/`, and every persisted variation is written there as
`<artifact_id>.<ext>`. Each variation's `ArtifactRef` reports `local_path` or
`export_error`. See [Tools](tools.md#writing-outputs-to-local-paths).

### Seedance variations

Seedance variations are fundamentally different from Seedream/Seed Audio
because each variation creates a **separate provider task**. They are not a
separate tool: call `seedance_create_task` with `variations` (1-5) and
optionally `variation_prompts` (exactly one per variation). The direct
result lists every variation in `tasks` (`index`, `task_id`, `request_id`,
`error`). `task_id` and `error` can coexist after an accepted task's
ownership-record failure: `submitted` counts known accepted IDs, while
`failed` counts entries with errors. These counts can overlap, so do not
subtract `failed` to decide how many tasks were accepted.

Budget-finalization exceptions log `ERROR` event `budget_finalization_failed`
without replacing the provider result/error or adding to `failed`. Failed
commit/release leaves conservative reserved allowance; pre-dispatch reservation
failures still fail closed. Cancellation cleanup is shielded best effort, not
a guarantee that no reserved rows remain.

Preserve every accepted ID and never resubmit it because ownership recording
failed. These `AcceptedTaskError` failures are ambiguous/nonretryable.
HTTP polling requires recorded ownership; otherwise reconcile directly with
the provider using task/request IDs. Trusted stdio permits unrecorded IDs,
but still rejects a recorded owner mismatch. A single-call failure remains error
`ToolResult` text containing known IDs, not structured success output.
Poll recorded task IDs at once with
`gen_task_get` (1-50 task IDs, one provider list call per page of 20;
`all_terminal` tells you when to stop, and `output_dir` writes finished videos
locally). **Never resubmit `seedance_create_task` to poll**: that starts new
billed tasks. Use `dry_run=true` first to check the request bodies and
estimated cost of every variation without billing. `draft=true` works with
variations; `draft_task_id` requires `variations=1`.

### Cost

All variation tools log a cost estimate before dispatching calls. The
estimate is based on the number of variations and the product type. Actual
billing is determined by the provider and reflected in the per-response
usage fields.

## Choosing the right mechanism

| Scenario | Use |
|---|---|
| Multiple images, same prompt, Lite or 4.x model | `max_images` on `seedream_generate_image` |
| Multiple images, 5.5 or Pro model | `variations` on `seedream_generate_image` |
| Per-variation prompts or seeds | `variations` plus `variation_prompts` (and `seed` on Seedream) |
| Multiple audio outputs | `variations` on `seed_audio_generate` |
| Check requests and cost first | `dry_run=true` on `seedream_generate_image` or `seedance_create_task` |
| Multiple video tasks | `seedance_create_task` with `variations` (1-5), then `gen_task_get` |

[`run_variation_batch`]: ../src/ark_mcp/tools/_parallel.py
