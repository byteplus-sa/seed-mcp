# Direct workflows and error handling

How to run work end to end: direct calls, the production workflows that
need record-keeping, retry and error rules, and practices the tool schemas do
not spell out. Parameters live in the tool schemas (see
[API reference](https://byteplus-sa.github.io/ark-mcp/api-reference/)); polling and
artifact recovery are in [polling-and-artifacts.md](polling-and-artifacts.md).

## Direct execution

**Both transports call the product tool directly, without MCP jobs or native tasks.**
For HTTP, read provider IDs from the direct result, poll with the same selected
provider key/client secret, keep persistence false and download URLs yourself.
All persistence/export instructions below describe local stdio.
Both transports reject explicit per-call `io.modelcontextprotocol/tasks` opt-in, including
on discovery, before provider dispatch, snapshot capture/save or queue creation.
Omit task opt-in; ordinary jobs are not an HTTP fallback.

For non-dry HTTP Seedance/OmniHuman creates, generate `idempotency_key` once
per intended whole call (16-128 ASCII letters, digits, `_` or `-`; UUID
recommended). Repeat identical arguments/key only for saved-success delivery
recovery, not polling. Replay checks ownership before any provider/Draft read.
Failed/partial/cancelled attempts are unresolved with known IDs, never
automatically resumed; do not change keys to bypass uncertain acceptance.
Keep the original provider/client credentials and same server state/HMAC
configuration. Seedance dry runs need no key or journal; stdio rejects keys.
The local examples below remain keyless.

Call with `{"input": {...}}`, check `is_error`, then read `structured_content`.
No MCP job IDs, worker snapshots or execution claims exist. Provider queues
and HTTP journal/ownership records remain separate.

- Owner-first admission waits up to `MCP_ADMISSION_TIMEOUT_SECONDS=2.0`
  (finite positive, max 30), then reserves budget after acquiring slots.
  `ADMISSION_TIMEOUT` means this attempt did not dispatch, not the whole batch.
- `MCP_TOOL_TIMEOUT_SECONDS=600.0` (finite positive, max 3600) starts at wrapper
  entry before credentials, journal and admission. Use client timeout 660
  seconds and compatible proxy settings.
- `TOOL_DEADLINE_EXCEEDED` retains mutation uncertainty and known safe IDs.
  External cancellation propagates; SDK/SQLite cleanup can exceed the
  cooperative deadline. Timeout does not cancel provider work.
- Never blindly resubmit. Poll known provider IDs or reconcile with the
  provider. Local calls have no submission journal or automatic replay.
- Local writes use live MCP roots or `OUTPUT_ROOTS`; persistence itself
  needs no output roots. See [local-output.md](local-output.md).

## Production workflows

### Resumable async generation

For Seedance and OmniHuman:

1. Check limits with `ark_list_models`; for Seedance and Seedream also run a
   `dry_run: true` call to confirm the request and `estimated_cost_usd`.
2. Submit directly and read every provider `task_id` from the
   direct result (check per-variation `error` and `failed`).
3. **Record before the first poll**: provider task ID(s), request IDs,
   request parameters, a prompt hash, and the intended output path in your
   manifest. This is what makes a restart recoverable.
4. Poll and persist as described in
   [polling-and-artifacts.md](polling-and-artifacts.md). While queued, relay
   `queue.hint`; the provider publishes no queue position or ETA.
5. On success record artifact ID, `local_path`, byte size, SHA-256, provider
   timestamps, and usage. Recover any output with `persistence="failed"` via
   `seed_media_persist_url` before its source URL expires.
6. A local watcher timeout is not a generation failure: resume `gen_task_get`
   with the existing ID. Create a new task only after the old one is terminal
   and another take is wanted.
7. Cancel or delete only when cleanup is explicitly wanted (see below).

### Seedance run: submit, poll, persist

1. Call `seedance_create_task` directly. The result lists `tasks[]`
   for a successful single call or variation batch. A variation can contain
   both `task_id` and `error` when accepted-task ownership recording fails.
   `submitted` counts known accepted IDs; `failed` counts entries with errors,
   so the counts can overlap. Single-call failures instead return error
   `ToolResult` text with any known accepted task/request IDs. Only accepted
   journal/ownership-record failures become outward `AcceptedTaskError` failures,
   which are ambiguous/nonretryable. Budget-finalization exceptions only log
   `budget_finalization_failed`, preserving the provider result/error without
   adding to `failed`.
2. Record every known ID, even alongside an error; never recreate accepted
   work. HTTP polling requires recorded ownership. If recording failed, reconcile
   directly with the provider using task/request IDs. Trusted stdio permits
   unrecorded IDs, not recorded owner mismatches. Otherwise poll **all
   IDs in one `gen_task_get` call** in the
   foreground (`persist_output` omitted) at `recommended_poll_after_ms` until
   `all_terminal`.
3. On stdio, persist: rerun `gen_task_get` directly with
   `persist_output=true` (add `output_dir` to also write the files locally,
   which needs live MCP roots or `OUTPUT_ROOTS`). Record the artifact IDs, or download the
   `video` output's `source_url` (valid about 24 h) yourself and record bytes,
   SHA-256 and `ffprobe` properties.
4. Draft flow (regular 2.5 only, not Flash): submit `draft=true` (480p), poll it to success,
   review the preview, then submit once with `draft_task_id` for the final
   render. The provider reuses the Draft's values, so omit the fields it
   fixes (and `variations`); omit `model` to reuse the Draft's model.
5. `gen_task_cancel_or_delete` is destructive and needs `expected_status` to
   match. Deleting makes the outputs unretrievable through `gen_task_get`, so
   persist first.

### Seedream edit flow

- One tool covers edit: pass the source image(s) in `images`; the first image
  is the edit target. Reference images accept HTTPS URLs or Base64, not
  native Seedance `asset://` references.
- For a targeted edit pass structured `point` or `bbox` (normalized 0-999,
  top-left origin; `round(pixel / dimension * 1000)`, capped at 999). **Do not
  write the markup into `prompt`**: the server prepends `Image 1<point>...`
  or `Image 1<bbox>...` itself, and applies it to every variation prompt.
- `background="transparent"` supports text-only generation or references
  without alpha on Seedream 5.5. On 5.0 Pro it is a transparency-preserving
  edit requiring exactly one PNG that already has transparent pixels.
  Both require `output_format` omitted or `png`.
- 5.5 defaults to `background="auto"`; use `generations[].images[].background`
  to read the actual returned background, not infer it from the request.
  `prompt_optimization` is omitted or `standard`, never `fast`.
- 5.5 supports size tiers `1K`, `1.5K`, `2K` and bounded custom dimensions;
  consult discovery. `auto` size and layer-decomposition/OCR controls are rejected.
- Use only a stable hashed `safety_identifier` (5.5/Pro, 1-64 non-space ASCII);
  previews/logs redact it, while `generations` preserves the provider echo.
- To iterate on a generated image, pass its provider URL (valid 24 h) or
  re-upload via `media_upload` and use the presigned URL.
- A fixed `seed` helps reproduce request settings, not guaranteed pixels. With
  `variations > 1`, `seed` is a base: `N` gives `N, N+1, ...`, `-1` picks a
  random recorded seed per variation, omitted leaves them unrecorded. On
  Seedream 5.5 and 5.0 Pro use `variations` instead of `max_images`.

### Seedream generate, review, edit

- Agree an explicit paid-attempt and estimated USD budget before iterating.
  Stop at either limit; never reroll
  automatically after byte-inspection or creative failures.
- Keep the original prompt privately with reference hashes and a lineage
  manifest. Record `generations[].request_id`, submitted `seed`,
  final `prompt_sha256` (including edit markup), `request_options`, usage,
  artifact ID and SHA-256. Omitted/random seeds are not recovered provider seeds.
- Check delivery errors, persistence and `images[].inspection` first.
  `verified` means valid bytes and checked claims, not visual acceptance.
  Provider reports and local measurements are separate; null is unknown.
- Review exact text and absence of forbidden text, counts, geometry,
  visibility, anatomy and composition with an authorized human or separately
  configured external reviewer. Use exported bytes or a provider URL;
  this server does not perform media review or OCR.
- Keep `Pass`, `Partial`, `Fail` and `Not evaluated` separate. A review refusal
  or unavailable reviewer is not a generation failure; exclude it from assessed
  denominators and do not bypass it.
- Make an authorized focused edit with `images` and structured `point`/`bbox`;
  retain the original and record parent artifact/hash, instruction, new request
  and artifact IDs, cost estimate and review as a new attempt.
- Only select outputs after acceptance. Check inline previews in published
  documents/sheets; upload success alone is insufficient. Publishing/link repair
  stays in the consumer integration. No native Seedream OCR/decomposition tool
  is exposed. Full workflow: [integration guide](https://byteplus-sa.github.io/ark-mcp/integration-guide/#seedream-review-and-edit).

### Asset-reference flow (Seedance `asset://`)

1. Obtain an existing usable provider asset through an authorized external
   workflow. Establish subject consent, rights and endpoint authorization there.
2. Pass its `asset://<id>` in Seedance `images`, `videos` or `audios`;
   refer to inputs as "Image 1" or "Video 1" by position.
3. Dry-run the request, then submit once and retain task IDs for polling.
   The server validates reference syntax but does not query asset status,
   permissions or project access.

This works on both transports with the normal ModelArk key. No asset
administration or asset-to-URL fallback is exposed. Ordinary uploads are
not provider assets. See [media-assets.md](media-assets.md).

### Variations and dry runs

- **No separate variation tools:** set `variations` (Seedance 1-5, each a
  separately billed task; Seedream 1-10; Seed Audio 1-5) with optional
  `variation_prompts` (exactly `variations` entries).
- Variations are independent and **partial failures are returned**, not
  raised. `error.phase` tells you what to do: `queued` (`QUEUE_TIMEOUT`) never
  started, safe to retry; `generating` may have completed, do not retry
  blindly; `persisting` means billed output was not stored.
  An HTTP Seedance key covers the whole batch, not individual variations.
  Partial results leave it unresolved; do not retry the batch or automatically
  create a new key for the missing entries.
- Write image/audio variations to a directory path ending in `/`.
- `dry_run: true` (Seedance, Seedream) validates against the model's limits
  and returns request bodies plus `estimated_cost_usd`, an estimate rather than
  billing or a provider quote. Seedream `preview.price_source` is `builtin`.
  Nothing is sent or billed.

### Generation record lifecycle

Use explicit states so a take is never mistaken for an approved one:
`ready` -> `submitted` -> `queued/running` -> `review` -> `approved/rejected`,
with `failed`, `cancelled`, `expired` as terminal failures. Record a take
under `outputs` while it is under review; set `selected_variant`/`approved`
only after a passing, authorized review. If the provider returns null or
incomplete settings, treat the submitted request as the intended parameters
and media inspection as the actual output properties.

### Post-generation media QA

Task success proves generation finished, not that the brief was met.

1. `ffprobe` the file: resolution, duration, frame rate, codecs, pixel format,
   audio streams.
2. Decode the whole file with FFmpeg; any decode error fails QA.
3. Watch it at normal speed and inspect critical motion, timing, camera,
   transitions, and audio. Contact sheets are for appearance only, not
   temporal evidence.
4. Check acceptance criteria (subject order, direction, boundary behaviour,
   forbidden elements, final location) and, with audio enabled, the audio
   stream itself.
5. Mark the take `review`; optionally make an H.264 proxy for HEVC masters
   and keep the original.

## Error handling

### Provider errors

Failures come back as tool results with `isError: true` and text of the form
`<provider> <operation> failed: <message> [code=..., http_status=...,
request_id=..., retryable=..., ambiguous_completion=...]`. There is no
structured error payload, so read the bracketed fields. **`request_id` is the
handle for reconciliation.** When `ambiguous_completion=True`, the operation
may have succeeded: inspect the task or resource before any retry.

An `ambiguous_completion=True` error naming an output audit
(`decision_in_reject_list`, code `55001310`) is the exception: it is a
terminal content rejection with no artifact or provider task to reconcile.
Mark the operation failed, diagnose, and never repeat the identical request.

### Retry policy

The retry wrapper retries only errors marked `retryable` **and not ambiguous**: up
to 3 attempts, exponential backoff from 0.25 s capped at 4 s with 20% jitter,
honoring `Retry-After` (also capped at 4 s). After that the error reaches you.

Uncertain mutation transport failures and malformed 2xx responses are
ambiguous/nonretryable.
Eligible 429 rejections, demonstrably pre-dispatch connection/pool failures and
reads retain bounded retries. Mutation 5xx responses may still carry
`retryable=true`, but `ambiguous_completion=true` prevents automatic retry.
Diagnostics are sanitized; never add blind client-side retries.
HTTP asynchronous-create receipt recovery is implemented; synchronous product
replay and complete crash recovery remain deferred. Journal claims never
auto-prune; `STATE_MAX_RECORDS` rejects new keys at capacity without blocking
existing-key reads. PostgreSQL/Redis are future scaling choices, not initial
requirements. See `specs/SPEC_HOSTED_BYOK.md#http-submission-safety` in the
selected checkout.

| Operation | Timeout after possible dispatch | Server retries? | You should |
|---|---|---|---|
| Create / generate / cancel / delete | `retryable=false`, `ambiguous_completion=true` | No | Reconcile by task or request ID; do not resubmit |
| Task polls (Seedance, OmniHuman) | `retryable=true`, `ambiguous_completion=false` | Yes | Poll again |

- A lost response may still hide accepted work; reconcile safe task/request IDs.
- Any `TIMEOUT` attempts to commit the budget reservation, since it may have
  been billed. Finalization failure leaves conservative reserved allowance,
  without replacing the original timeout.
- Output downloads are retried separately (`ARTIFACT_DOWNLOAD_MAX_ATTEMPTS`,
  default 3); expired, untrusted, or oversized sources are not.

### Budget rejections

With `DAILY_BUDGET_USD` above 0 the server tracks per-principal daily spend
(UTC day), scoped by credential tenant/client owner on HTTP, and rejects
a request whose estimate would exceed it, before any
provider call ("Daily budget of $X would be exceeded"). At `0` (default) usage
is recorded without a spending-limit rejection; a successful reservation is
still required. Wait for the UTC rollover or raise the limit after a budget rejection.

Reservation failures still fail closed before provider dispatch. Later
commit/release exceptions log `ERROR` event `budget_finalization_failed` with
safe provider/action/reservation ID fields; they do not replace the provider
result/error or create variation failures. Failed finalization leaves allowance
conservatively reserved. Cancellation cleanup is shielded best effort, not a
guarantee that no reserved rows remain. Never regenerate accepted work to
recover from a ledger problem.

### Common issues

| Symptom | Cause | Fix |
|---|---|---|
| Tool missing from the tool list | Missing provider key, OmniHuman flag, or selected TOS/S3 configuration | Check `ark_list_models.services` and [environment.md](environment.md); restart after approved configuration changes |
| `Request is not valid for model ...` (Seedance, Seedream) | Request breaks that model's limits; every violation is listed | Fix each item or pick another model from `ark_list_models`; re-check with `dry_run: true` |
| Model not found | Unknown ID (exact IDs only) | Use the did-you-mean hint or `ark_list_models` |
| Artifact has `persistence_error` | Billed output, storage failed after retries | `id="provider-url"`: `seed_media_persist_url` before `source_url_expires_at`; `id="inline-fallback"`: bytes are in `fallback_data` |
| `output_path` rejected | No MCP roots and no `OUTPUT_ROOTS`, relative path, outside roots, HTTP transport, or `persist=false` | Absolute path inside a root on stdio, set `OUTPUT_ROOTS`, `overwrite=true` to replace a different file |
| `media_upload` rejected for `MEDIA_UPLOAD_BATCH_MAX_BYTES` | Total size over the cap; nothing uploaded | Split into smaller calls |
| `media_upload` succeeds with `failed > 0` | Some items failed (validation, missing file, uninferable `mime_type`, provider) | Read `items[].error`; re-upload only those, retrying when `retryable=true` |
| Presigned URL expired / `NOT_OWNED` | TTL elapsed (default 30 min) / key not uploaded by this caller | `media_presign` with the `object_keys`; re-upload foreign keys |
| `omnihuman_create_task` rejects a `seed-media://` input | Filesystem artifact backend cannot mint provider-readable URLs | `ARTIFACT_BACKEND=object_storage`, or `media_upload` and pass the presigned URL |
| `omnihuman_get_task` fails with `InvalidParameter ... audio` | Audio is validated only after submission (4-300 s, wav/mp3, under 15 MB; 300 s WAV is 26-58 MB) | Fix the audio (MP3 or shorter) and resubmit; never unchanged |
| OmniHuman error `50510` | Provider content pre-filter rejected the image or audio | Use different compliant inputs; never retry unchanged |
| HTTP credential rejection | Missing or malformed selected provider key/client secret | Configure private BYOK headers; never use `Authorization` or paste values into chat |
| Asset administration unavailable | Not part of this server | Use an authorized provider console or external workflow |

## Best practices beyond the schemas

- **For ordinary Seedance URL references, upload once and presign per shot.**
  Store each `object_key` from one `media_upload` call (check `failed`) in a
  project reference registry; before each shot call `media_presign` for the
  keys it needs and submit immediately. Use a long `expires_in_seconds` (for
  example 3600) for references, which are fetched asynchronously. Existing
  native `asset://` references do not need an ordinary upload or presign.
- **Verify saved media, not task status** (see the QA sections).
- **Persist before cleaning up.** Provider URLs expire (2 h audio, 24 h
  ModelArk image/video, 1 h OmniHuman); `gen_task_cancel_or_delete` removes retrievable outputs.
- **Write straight to the project on stdio** with `output_path`,
  `output_dir` instead of a follow-up export, and check
  `local_path` / `export_error`. See [local-output.md](local-output.md).
