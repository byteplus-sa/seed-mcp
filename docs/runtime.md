# Runtime Services

The server lifespan owns a single `RuntimeServices` object
(`src/ark_mcp/runtime.py`) that is built once at startup and closed at
shutdown. Every tool retrieves it via `get_runtime(ctx)`. This document
describes its operational services, including concurrency limiting, the daily
budget ledger, provider-task and object-key ownership, persistence caching,
per-task persistence single-flight, the HTTP submission journal, and the provider retry policy.

HTTP is the forward-only [BYOK foundation](../specs/SPEC_HOSTED_BYOK.md):
foreground direct calls with request-key gateways, minimal scoped SQLite state,
no jobs/native tasks, storage/artifact tools or resources. Artifact caches,
and object storage below are local stdio capabilities. Both transports execute
directly, with no MCP jobs, native tasks, snapshots or execution claims.
Fresh state is required; no old-schema migration exists.

## Request Configuration

HTTP middleware binds the receiving server's `Settings` with `settings_scope`
for the request lifetime and resets it in `finally`. `get_settings()` resolves
that context before process defaults. With scoped settings,
`get_capability_registry()` builds from those settings instead of reusing the
process-default registry. Concurrent server instances therefore keep their
configured model bindings and defaults isolated.

Anonymous `ark_list_models` uses this same scope and lists configured bindings
without environment provider keys. `services[].enabled` describes registered
services, not customer entitlement or successful provider authentication.
Per-call endpoint headers select an exact binding from this server's registry;
an explicit tool `model` wins.

## State Storage

All state lives in a single SQLite database at
`<artifact_dir>/runtime.sqlite3` (default `artifact_dir` is `~/.seed-mcp/artifacts`),
shared by the ownership stores, budget ledger, HTTP submission journal and
task-artifact cache. Provider task ownership is retained independently of
direct-call execution. The
database is opened in WAL mode (`PRAGMA journal_mode=WAL`) with a
`busy_timeout`; each store's
synchronous `sqlite3.Connection` is guarded by a per-instance `asyncio.Lock`
and every query is dispatched to a worker thread via `asyncio.to_thread`, so
SQLite access never blocks the event loop. Shared `sqlite_io.drain_task`
drains worker completion before releasing the connection lock or propagating
cancellation, including repeated cancellation. This serialization applies to
the runtime stores and submission journal. These stores are still
**single-process only** — horizontal scaling requires a distributed
replacement.

### HTTP State Lease

`RuntimeStateLease` (`runtime_lock.py`) holds `runtime.sqlite3.lock` for the
whole HTTP runtime. A nonblocking hard filesystem lock is acquired **before**
opening any store or running submission recovery. Contention fails startup
with fixed text. Partial startup failure and cancellation drain acquisition/
cleanup and release the lease; normal shutdown releases it after all state
users close. Never unlink or replace a live lock file. The file can remain
after process exit; its presence alone does not mean a process owns the lock.

This is local block-storage protection, not distributed fencing. Do not use a
network filesystem, multiple Uvicorn workers or multiple application replicas.
Stdio does not acquire this HTTP lease; never point it at an active HTTP
state directory. The [VKE chart](byteplus-terraform.md#chart-inputs-and-network)
uses one StatefulSet and retained ext4 ReadWriteOnce EBS.

## `RuntimeServices` fields

| Field | Type | Built from |
|---|---|---|
| `settings` | `Settings` | input settings |
| `artifact_store` | `FilesystemArtifactStore` | `FilesystemArtifactStore(artifact_dir, ttl_seconds, downloader)` |
| `safe_downloader` | `SafeDownloader` | `SafeDownloader(timeout, connect_timeout)` |
| `ownership_store` | `SQLiteTaskOwnershipStore` | `SQLiteTaskOwnershipStore(database_path)` |
| `object_key_ownership_store` | `SQLiteObjectKeyOwnershipStore` | `SQLiteObjectKeyOwnershipStore(database_path)` |
| `budget_ledger` | `BudgetLedger` | `BudgetLedger(database_path, daily_limit_usd)` |
| `provider_limiters` | `ProviderLimiters` | `ProviderLimiters(provider_limit, principal_limit, admission_timeout_seconds)` |
| `task_artifact_cache` | `TaskArtifactCache` | `SQLiteTaskArtifactCache(database_path, ttl_seconds, max_size)` |
| `task_artifact_locks` | `TaskArtifactPersistenceLocks` | process-local lock registry |
| `submission_store` | `SQLiteSubmissionStore \| None` | HTTP only: `SQLiteSubmissionStore(database_path, max_records=state_max_records)` in a worker thread; stdio defaults to `None` |
| `state_lease` | `RuntimeStateLease \| None` | HTTP only: exclusive filesystem lease before stores/recovery |
| `metrics_listener` | `MetricsListener \| None` | HTTP only when `MCP_METRICS_PORT` is nonzero; loopback listener with owned thread |

`close_runtime_services` first drains the optional metrics listener, then `artifact_store`,
`ownership_store`, `object_key_ownership_store`, `budget_ledger`, and
`task_artifact_cache`, then `submission_store` when present, the downloader
and finally the lease. Journal close drains admitted operations before closing
its connection. Artifact-store close also closes its downloader. Cleanup
drains despite repeated cancellation; the same close task is reused.
The provider/principal limiters and per-task lock registry have no close method.

## Concurrency limiters (`ProviderLimiters`)

Two distinct layers, acquired owner-first for billable calls:

- **Provider-level** — one global `asyncio.Semaphore` per provider bucket:
  `"modelark"`, `"seed-speech"`, `"vision-cv"`, `"tos"`, and `"s3"`.
  Each is independently sized to `provider_limit`, so the default cap is five
  concurrent calls per provider rather than five shared across all providers.
- **Principal-level** — one `asyncio.Semaphore(principal_limit)` per
  owner, keyed by `(tenant_id, principal_id)` in a bounded registry.
  Active holders and waiters pin the same entry; idle entries are removed.

`acquire(provider, owner)` is an async context manager that holds **both**
the principal's semaphore and then the provider bucket semaphore for the
duration of the call. A single admission deadline covers both waits, not
provider execution after acquisition. Partial acquisition is released on
timeout/error/cancellation. Waiting for an owner slot never occupies a global
provider slot, so a same-owner backlog cannot monopolize that provider.

For a **local principal** (stdio transport), the
per-principal semaphore is **skipped**: a single trusted local caller is
bounded only by the provider limit. Without this, the default
`PRINCIPAL_MAX_CONCURRENCY=3` would silently cap *all* concurrent calls across
every provider at 3 — below the per-provider limit of 5 — making parallel
local generation appear to "serialize under load." The per-principal bound
applies to HTTP owners derived from the selected provider credential and
client secret. Unrelated provider keys do not change that scope.

| Env var | Default | Constraint | Used as |
|---|---|---|---|
| `PROVIDER_MAX_CONCURRENCY` | `5` | `ge=1` | per-bucket provider limit |
| `PRINCIPAL_MAX_CONCURRENCY` | `3` | `ge=1` | derived HTTP owner limit; skipped on local stdio |

The owner registry defaults to capacity 10,000. Active/waiting entries cannot
be evicted and replaced with independent semaphores. A new owner beyond
capacity receives `ADMISSION_CAPACITY_EXCEEDED`; a slot-wait expiry receives
`ADMISSION_TIMEOUT`. Both are `ProviderError`, operation `admission`,
`retryable=true`, `ambiguous_completion=false`: this attempt did not dispatch.
Other variations may already have dispatched; no automatic admission retry
loop is added.

> For parallel variation tools, a third local `asyncio.Semaphore(max_concurrent=5)`
> is created per batch by `run_variation_batch` (see [Parallel
> variations](#parallel-variations-tools_parallelpy)). It composes with — and is independent
> of — these provider/principal limiters.

## Concurrency and timeouts

**Both transports execute ordinary tool calls directly.** Provider latency,
admission and the cooperative whole-call deadline are separate bounds:

| Bound | Default | Code | Effect |
|---|---|---|---|
| Provider admission | `MCP_ADMISSION_TIMEOUT_SECONDS=2.0` | `runtime.py::ProviderLimiters` | Finite positive seconds, max 30; combined owner-first/provider wait |
| Whole tool | `MCP_TOOL_TIMEOUT_SECONDS=600.0` | `execution.py::run_direct_call` | Finite positive seconds, max 3600; cooperative deadline from wrapper entry |
| Provider request | `BYTEPLUS_REQUEST_TIMEOUT_MS=600000` (10 min), connect `BYTEPLUS_CONNECT_TIMEOUT_MS=10000` | `config/env.py` | Per HTTP call to a provider; timeouts are classified in [Error taxonomy](#error-taxonomy) |
| HTTP graceful shutdown | `max(tool seconds, provider milliseconds / 1000) + 30`, default 630 s | `__main__.py::graceful_shutdown_timeout_seconds` | Cooperative drain allowance; chart pod grace uses max + 60, default 660 s |
| SQLite lock wait | `busy_timeout=5000` ms | `runtime.py::_open_sqlite_connection` | A blocked writer waits up to 5 s in its worker thread, never on the event loop |
| HTTP request body | `MCP_HTTP_MAX_BODY_BYTES=2097152` (2 MiB) | `config/env.py` | Positive streamed body cap |
| HTTP admission | `MCP_HTTP_MAX_IN_FLIGHT=64`, `RATE_LIMIT_RPM=60` | `security/http_middleware.py` | Positive global in-flight and per-IP rate bounds, including discovery |
| Retained state | `STATE_MAX_RECORDS=100000` | `runtime.py`, `submission_store.py` | Positive capacity; never evict live owners or journal claims; existing journal keys remain readable at capacity |
| Variation batch | `variation_batch_deadline(...)` | `tools/_parallel.py` | See [Parallel variations](#parallel-variations-tools_parallelpy) |

- **Use client timeout 660 seconds** with the default 600-second tool deadline,
  and compatible proxy timeouts. The tool timer starts after MCP parsing,
  before credentials, bindings, journal, admission and execution.
- **Cancellation is cooperative.** SQLite and SDK threads drain before locks,
  slots or clients are released, including repeated cancellation. Cleanup can
  exceed the nominal deadline; it is not a hard kill or provider cancellation.
- `TOOL_DEADLINE_EXCEEDED` is text-only, preserving possible mutation and known
  safe accepted IDs. Pre-dispatch/read-only expiry does not claim billed work
  began. External cancellation propagates; inner provider timeouts retain
  their normalized errors. Never blindly resubmit after a lost response.
- ModelArk polling and discovery do not wait on saturated generation slots.
  They are still subject to HTTP global in-flight/body/rate bounds.
  See [Direct Execution](../specs/SPEC_DIRECT_EXECUTION.md).
- **Large media should not travel inside JSON-RPC.** Use `media_upload` with a
  file path (stdio) or the presign and direct-upload path; the body limit only
  bounds inlined Base64.

## Artifact persistence single-flight

`RuntimeServices.task_artifact_locks` is a process-local
`TaskArtifactPersistenceLocks` registry keyed by `(provider, task_id)`. A lock
entry exists only while a holder or waiter is active and is removed when its
user count reaches zero. Provider-task polling uses it to recheck the durable
task-artifact cache inside the critical section and share a just-created
artifact with concurrent waiters, while different task IDs remain concurrent.
Cache failures are best-effort: they emit safe warnings but do not erase a
successful provider result or an artifact that was already created.

This coordination is intentionally single-process, matching the current SQLite
state backend. A future distributed state backend requires a distributed
single-flight mechanism.

## Daily budget + cost estimation

### Budget ledger (`BudgetLedger`)

SQLite-backed, same file as the ownership store. Schema:

```sql
CREATE TABLE budget_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_date TEXT NOT NULL,        -- UTC date (ISO)
    principal_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    product TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('reserved', 'committed', 'released'))
)
```

Three-state lifecycle: `reserved` → `committed` (charged) **or**
`reserved` → `released` (rolled back). Only rows with `status IN
('reserved', 'committed')` count against the limit.

- `reserve(owner, estimate)` — sums the principal's spend for the current
  UTC date; if a configured limit exists and `current + amount` would exceed
  it, increments `ark_mcp_budget_rejections_total{product}` and raises
  `BudgetExceededError` **before** the provider is called. Otherwise inserts
  a `reserved` row and returns a `BudgetReservation`.
- `commit(reservation)` — marks the row `committed`.
- `release(reservation)` — marks the row `released`.

| Env var | Default | Behavior |
|---|---|---|
| `DAILY_BUDGET_USD` | `0.0` | Per-principal UTC daily limit. `0.0` (and any falsy value) normalizes to `None` → **record-only mode** (no spending-limit rejection; a successful reservation is still required). A positive value enables **reject mode**. |

The daily window is the UTC calendar date, scoped per `(principal_id, tenant_id)`.
On HTTP those values derive from the selected provider credential and client
secret. Credential or HMAC key/version changes change scope. A new client secret
can create another owner; this is not a provider-account spending ceiling.

### Cost estimation (`tools/_cost.py`)

The estimator behind the daily budget and cost log uses built-in heuristics
only. Discovery returns no pricing fields, and no operator-account price
refresher runs. `price_source` is `builtin`. Estimates are not provider
quotes, settlement amounts or guarantees of an actual spend ceiling.

**Built-in rates:**

| Constant | Value |
|---|---|
| `COST_PER_IMAGE` | `0.03` USD |
| `COST_PER_AUDIO_SECOND` | `0.0031` USD |
| `COST_PER_VIDEO_TASK` | `0.07` USD (`0.35` for Seedance 2.5) |
| `DEFAULT_MAX_CONCURRENT` | `5` |

`estimate_cost(product, variations, ..., model_id=None)`:

| `product` | Formula |
|---|---|
| `"image"` | `round(variations * 0.03, 4)` |
| `"audio"` | `round(variations * max(duration_seconds, 10) * 0.0031, 2)` — **floor of 10 seconds per variation** |
| `"video"` | `round(variations * 0.07, 2)`; regular 2.5 and Flash use `0.35` per task, selected by registry family; a registered model-specific override wins |
| (any other) | `0.0` |

Video estimates do not account for resolution or duration. Flash uses the
static 2.5 per-task estimate, not its token-based provider price.

## Provider task ownership (`SQLiteTaskOwnershipStore`)

Ownership of asynchronous provider task IDs, so one principal cannot read,
cancel, retrieve, or delete another's tasks. Schema:

```sql
CREATE TABLE IF NOT EXISTS task_ownership (
    provider TEXT NOT NULL,
    task_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(provider, tenant_id, task_id)
)
```

| Method | Behavior |
|---|---|
| `record(provider, task_id, owner)` | Records within the credential tenant; an existing different principal is never reassigned. Capacity or store errors fail closed. |
| `require_owner(provider, task_id, owner)` | Row missing: if `owner.is_local` returns silently (local mode is permissive for unrecorded tasks), else `PermissionError`. Row present but mismatched: `PermissionError("Task is not owned by the current principal.")`. |
| `list_task_ids(provider, owner)` | returns task IDs for the provider and `(principal_id, tenant_id)`. |
| `ping()` | `SELECT 1` liveness probe (used by the `/ready` route). |
| `close()` | closes the connection. |

Every lookup is scoped by `provider`, `tenant_id` and `task_id`; owner listings also require
`principal_id`. The `is_local` shortcut only affects the
missing-row branch — a row that exists and belongs to someone else still raises,
even in local mode.

> This is distinct from **artifact ownership**, which is stored in
> `.meta.json` sidecars next to the artifact bytes
> (`artifacts/filesystem_store.py`). See [artifacts.md](artifacts.md).

## HTTP Submission Journal

`submissions.execute_submission(ctx, tool_name, request, call)` wraps only
HTTP Seedance and OmniHuman creates. Non-dry calls require `idempotency_key`
(16-128 ASCII letters, digits, `_` or `-`; UUID recommended). Seedance dry
runs bypass the journal without consuming a key. Stdio rejects supplied keys.
The [durable contract](../specs/SPEC_HOSTED_BYOK.md#http-submission-safety)
defines scoping, fingerprints and error codes.

`SQLiteSubmissionStore` commits a root claim for the whole batch before handler
entry, including before Draft lookup. Domain-separated HMAC digests cover the
key and canonical input/defaults/effective model; no raw prompts, media,
credentials, idempotency keys or error messages are journaled.
`http_submissions` holds scoped claims and bounded success JSON;
`http_submission_tasks` holds up to five safe accepted task/request-ID pairs.
The journal uses WAL, `synchronous=FULL`, a 5000 ms busy timeout and
cancellation-safe per-connection serialization of worker-thread operations.

| Method | Behavior |
| --- | --- |
| `claim(...) -> (SubmissionRecord, bool)` | `BEGIN IMMEDIATE`; return an existing matching claim first, reject changed input, or commit a new `running` claim subject to capacity |
| `get(submission_id)` | Read a consistent internal receipt snapshot |
| `record_task(submission_id, task_id, request_id)` | Retain bounded, immutable accepted IDs before ownership recording |
| `succeed(submission_id, response_json)` | Save at most 32 KiB of validated success JSON; only `running` can become `succeeded` |
| `mark_unresolved(submission_id)` | Transition `running` to `unresolved`, never demote saved success |
| `close()` | Drain pending operations and close the connection |

Only complete successful receipts replay, after every task's existing ownership
passes. Replay never enters the handler, contacts upstream, re-fetches a Draft
or repairs ownership. Repeating identical arguments/key recovers delivery,
not current provider status; poll task IDs normally after recovery.
Failures, partial batches and cancellation become unresolved, with known IDs
but no automatic resume. On startup, leftover running claims become unresolved.
If finalization cannot save success, the first successful provider result is
still returned, while repeated calls fail closed.

Claims never expire or auto-prune. `STATE_MAX_RECORDS` caps journal claims
independently of other state tables; at capacity existing keys and owned task
reads still work, but new keys fail before dispatch. Ownership retention is
separate: expired ownership blocks receipt replay. Keep the same SQLite volume,
HMAC key/version and original client/provider credentials. Deleting claims to
free capacity can permit duplicate submissions; capacity management remains
an operational follow-up.

## Persistence cache

`RuntimeServices.task_artifact_cache` is a `SQLiteTaskArtifactCache` backed by
the same `runtime.sqlite3` database as the ownership store and budget ledger.
Schema:

```sql
CREATE TABLE IF NOT EXISTS task_artifacts (
    provider TEXT NOT NULL,
    task_id TEXT NOT NULL,
    artifacts_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(provider, task_id)
)
```

It caches provider task lookups → artifact references (`dict[str, ArtifactRef | None]`).
The TTL defaults to 86,400 seconds (24h), matching the longest provider media-URL
expiry window (24h for image/video; audio URLs expire in 2h), so resolved artifact
references for a provider task ID are not re-resolved while still valid. Entries
older than `PERSISTENCE_CACHE_TTL_SECONDS` are lazily ignored on read. When the
row count exceeds `PERSISTENCE_CACHE_MAX_SIZE`, the oldest entries are evicted.

Unlike the previous in-memory `TTLCache`, the SQLite-backed cache **survives
server restarts** — a restart no longer loses cached task→artifact mappings.

| Env var | Default | Used as |
|---|---|---|
| `PERSISTENCE_CACHE_MAX_SIZE` | `10_000` | max rows before oldest eviction |
| `PERSISTENCE_CACHE_TTL_SECONDS` | `86_400` | TTL in seconds; entries older than this are ignored on read |

## Retry policy (`providers/retry.py`)

`RetryPolicy` is a frozen dataclass with hard-coded defaults (no env vars):

| Field | Default |
|---|---|
| `max_attempts` | `3` |
| `base_delay_seconds` | `0.25` |
| `max_delay_seconds` | `4.0` |
| `jitter_ratio` | `0.2` |
| `retry_timeouts` | `True` |

`call_with_retry(operation, *, policy=None, sleep=asyncio.sleep,
random_value=random.random)`:

- **Only `ProviderError` is retried**, and only when `exc.retryable` **and**
  `not exc.ambiguous_completion` **and** `attempt < max_attempts` **and**
  (`policy.retry_timeouts` or `exc.code != "TIMEOUT"`).
  Eligible 429 rejections can be retried. Mutation 5xx responses remain
  `retryable=true` in normalized HTTP errors but also have
  `ambiguous_completion=True`, so they are never automatically retried.
  Reconcile via the task ID / request ID instead of risking duplicate billing.
- Any non-`ProviderError` propagates immediately (no retry, no wrapping).
- **Backoff**:
  - If `exc.error.retry_after_seconds is not None` (provider `Retry-After`):
    `delay = min(retry_after_seconds, max_delay_seconds)` — **no jitter**.
  - Otherwise exponential with symmetric jitter:
    `base = min(base_delay * 2**(attempt-1), max_delay)`;
    `jitter = base * jitter_ratio * (random*2 - 1)`;
    `delay = max(0.0, base + jitter)`.
- Each retry increments `ark_mcp_retry_attempts_total{provider, operation}`.

Mutation read/write/protocol transport failures with uncertain acceptance
and malformed 2xx responses are ambiguous/nonretryable. Demonstrably pre-dispatch connection/pool
failures remain eligible for bounded retries subject to the timeout policy above.
Diagnostics omit raw exceptions, credentials and credential-bearing URLs.
Keep safe request IDs for reconciliation. Provider retries do not supply
idempotency or exactly-once billing. The separate HTTP submission journal
covers only asynchronous creates; do not add blind client-side retries.

## Billable call composition (`billed_provider_slot`)

A single async context manager ties the above together:

```python
async with billed_provider_slot(ctx, provider=..., product=..., estimated_cost_usd=...):
    result = await provider_call()
```

The context manager acquires the owner slot, then provider slot, and only
then reserves budget. The caller runs the provider operation after reservation.
Each gateway marks dispatch semantically; a read-only status POST is not a
mutation. Seedance/OmniHuman capture safe accepted IDs synchronously inside
the slot, before the next await or budget-finalization step.

Outcome handling (commit/release are best-effort finalization attempts):

| Outcome | Attempted budget action |
|---|---|
| Success | `commit` (charged) |
| `ProviderError` with `ambiguous_completion` | `commit` (treats as billable — may have succeeded) |
| `ProviderError` with `code="TIMEOUT"` (any, including retryable read timeouts) | `commit` (a timed-out completion may still have consumed billable tokens) |
| Other `ProviderError` | `release` |
| Cancellation after reservation and handler entry | `commit` conservatively; this alone does not prove dispatch |
| Cancellation while still waiting for a limiter slot | No budget reservation exists |
| Cancellation during reservation | Drain reservation, then release any known reservation best-effort; never dispatch |
| Any other exception | `release` |

Reservation failures still fail closed before provider dispatch. After reservation,
commit/release exceptions log `ERROR` event `budget_finalization_failed` with only
safe `provider`, `action` and `reservation_id` fields, without raw exception text.
They do not replace the provider result or original error, raise `AcceptedTaskError`,
or add a variation failure. A failed commit/release leaves the allowance
conservatively reserved and counted against the daily limit.

The original exception is re-raised on error or cancellation. Reservation
and finalization tasks drain through repeated cancellation. Cleanup is best
effort and may exceed the cooperative deadline; it does not guarantee that
no `reserved` rows remain. Admission stays held during finalization and SDK drain.

Seedance proceeds to the shared `record_accepted_task` helper after budget
finalization, even if finalization logged a failure. OmniHuman uses the same
helper. On HTTP, task/request IDs must match `[A-Za-z0-9._:-]{1,256}` and
contain no request/operator secrets before either write. Unsafe IDs produce
`UNSAFE_TASK_RECEIPT` without echo or persistence, leaving acceptance ambiguous.
Safe IDs are journaled before ownership; a journal-write failure still attempts
ownership recording. Either persistence failure becomes an
`AcceptedTaskError` (`SUBMISSION_RECORD_FAILED` or `OWNERSHIP_RECORD_FAILED`, `retryable=false`,
`ambiguous_completion=true`), retaining the accepted task ID and available
request ID without internal resubmission. A Seedance variation retains `task_id`
and `request_id` alongside `error`; `submitted` counts known IDs and `failed`
counts entries with errors, so a journal/ownership error can count in both.
A single-call failure remains an error `ToolResult` with IDs in its text rather
than a structured success response. HTTP polling still requires recorded
ownership; otherwise reconcile directly with the provider. Trusted stdio
permits unrecorded IDs, not recorded owner mismatches.

## Error taxonomy

| Class | Module | Raised by | Meaning |
|---|---|---|---|
| `ProviderError` | `domain/errors.py` | provider gateways + transport normalizers | wraps a `NormalizedProviderError`; the single retryable error type |
| `AcceptedTaskError` | `domain/errors.py` (extends `ProviderError`) | `record_accepted_task` | accepted task journal/ownership recording failed; retains safe task/request IDs, ambiguous and nonretryable |
| `BudgetExceededError` | `runtime.py` (extends `ValueError`) | `BudgetLedger.reserve` | daily budget would be exceeded; raised before dispatch |
| `ValueError` | builtin | `ProviderLimiters`, `RetryPolicy`, `resolve_prompts` | config/argument validation |
| `RuntimeError` | builtin | `get_runtime`, `BudgetLedger.reserve` | missing runtime services / reservation ID |
| `PermissionError` | builtin | `get_principal`, `require_owner` | missing token, missing principal/tenant claims, ownership mismatch |

`NormalizedProviderError` carries: `provider` (including `modelark`, `seed-speech`,
`byteplus-vision-cv`, `tos` and `s3`),
`operation`, `http_status`, `code`, `message`, `request_id`, `retryable`,
`ambiguous_completion`, `retry_after_seconds`. Transport-layer normalizers in
`BaseHttpGateway` follow the table below. The Vision AI error provider label
`byteplus-vision-cv` is distinct from its concurrency limiter bucket `vision-cv`.

| Method | `code` | `retryable` | `ambiguous_completion` |
|---|---|---|---|
| `normalize_timeout(op)` (mutation, default `side_effect=True`) | `TIMEOUT` | `False` | `True` |
| `normalize_timeout(op, side_effect=False)` (read-only) | `TIMEOUT` | `True` | `False` |
| `normalize_connection_error` (pre-dispatch) | `CONNECTION_ERROR` | `True` | `False` |
| `normalize_transport_error` (uncertain mutation) | `TRANSPORT_ERROR` | `False` | `True` |
| `invalid_response` (malformed mutation 2xx) | `INVALID_RESPONSE` | `False` | `True` |

Timeout classification after possible dispatch depends on whether the call can
change provider state or consume billable inference:

| Call | Examples | Timeout result | Auto-retried? |
|---|---|---|---|
| Mutation | Seedance/OmniHuman create, cancel, delete; Seedream/Seed Audio generate | `retryable=False`, `ambiguous_completion=True` | No — reconcile by task/request ID |
| Read-only poll | Seedance `get_task`/`list_tasks`, OmniHuman status | `retryable=True`, `ambiguous_completion=False` | Yes |

## Parallel variations (`tools/_parallel.py`)

Re-exports `DEFAULT_MAX_CONCURRENT = 5`.

- **`generate_seeds(...)`** — derives Seedream variation seeds from
  the request's `seed` (the base seed): `None` → provider-randomized (seed
  not recorded); `-1` → per-variation `secrets.randbelow(2**31)` (recorded);
  `N` → deterministic `(N + i) % 2**31`.
- **`resolve_prompts(base_prompt, variation_prompts, count)`** — uses
  `variation_prompts` if given; else `[base_prompt] * count`; raises if
  neither is provided.
- **`gather_with_timeout(coros, timeout)`** — per-coroutine
  `asyncio.wait_for` + `asyncio.gather(..., return_exceptions=True)`; returns
  exceptions and `asyncio.TimeoutError` **as elements**, never raises. Still
  exported but no longer used by the variation tools.
- **`variation_batch_deadline(count, settings, *, max_concurrent=5,
  provider_attempts=3, persists=True)`** — `ceil(count / max_concurrent) ×
  (request_timeout × provider_attempts + download_timeout ×
  download_attempts)`; the download term is dropped when `persists=False`
  (Seedance variations).
- **`run_variation_batch(count, factory, *, batch_deadline,
  max_concurrent=5)`** — local `asyncio.Semaphore(max_concurrent)` around
  `factory(idx, progress)`. There is no separate per-variation timer, but
  provider admission is bounded and the whole-tool deadline includes slot
  waiting. At `batch_deadline`, unfinished variations are cancelled and
  classified by `VariationProgress.phase`: `queued` → `QUEUE_TIMEOUT`
  (retryable), `generating`/`persisting` → `TIMEOUT` (ambiguous), or the
  factory's recorded `partial` result (an unpersisted provider-URL artifact)
  when persisting. Unexpected exceptions map to `GATHER_ERROR`. A variation counts as succeeded iff it
  produced an `artifact` **or** a `task_id`. Returns `VariationSummary(total,
  succeeded, failed, variations)`. One variation failing never breaks the
  others; the batch always returns exactly `count` entries.

Seedance's outward `submitted`/`failed` counters are computed independently
from those entries: an accepted task with a journal/ownership-record error counts in
both. Budget-finalization log events do not add failures to these counters.

See [api-reference.md](api-reference.md) for `VariationResult` /
`VariationSummary` / `VariationError` field tables.

The outer cooperative tool deadline can expire before that batch safety net.
It returns text-only `TOOL_DEADLINE_EXCEEDED` with uncertainty and known safe
accepted IDs, not a guaranteed complete variation summary. Cleanup can exceed
the deadline. Preserve partial acceptance; never blindly rerun the batch.


## Direct execution state

`execution.py` maintains ephemeral ContextVar state shared with variation
children: monotonic deadline, possible-mutation flag and bounded safe accepted
receipts. It is invalidated when the call exits. No credentials, payloads,
snapshots, durable execution claims or MCP job records are created.

`before_provider_request(side_effect=...)` checks expiry before dispatch;
`record_accepted_receipt` retains safe IDs. `runtime.capture_accepted_task`
validates IDs before capture, including checks against startup/request secrets.
After a handler suppresses cancellation, the wrapper rechecks expiry.
Neither transport accepts explicit `io.modelcontextprotocol/tasks` opt-in.
Provider ownership and the HTTP journal are separate durable state and remain
intact. See [Direct Execution](../specs/SPEC_DIRECT_EXECUTION.md).

## HTTP Readiness and Recovery

HTTP `/health` and `/ready` expose minimal process/state readiness and never
probe providers. `/metrics` and configuration-detail resources are unavailable
on public HTTP. Positive state admission reduces capacity failures before
dispatch, but post-acceptance record failures remain ambiguous.

VKE Caddy exposes `/mcp` and `/health` only; `/ready` remains an internal
loopback exec probe. `MCP_METRICS_PORT` defaults to `0` (disabled) and otherwise
binds only `127.0.0.1` on ports 1024-65535 for the HTTP runtime. Stdio never
starts this listener. The listener drains its thread on shutdown and is not
registered on the main app. Use [authorized private access](observability.md#metrics-endpoint),
never a public Service.

Keys are request-only, not persisted.
HTTP asynchronous-create idempotency is the first slice described above.
Synchronous product replay and complete crash recovery remain deferred,
including the acceptance-to-first-ID-write crash gap and unknown-task
reconciliation. PostgreSQL/Redis are future scaling choices, not initial
requirements. Multi-replica support and public-launch readiness are not claimed.

## Read-Only State Inspection

The standalone stdlib-only `scripts/inspect_runtime_state.py` accepts explicit
`--database` (alias `--path`), `--capacity` and optional `--timeout-seconds`.
It does not import Settings, load `.env`, start the app or trigger recovery.
Run against an authorized database path or a consistent isolated backup:

```bash
python scripts/inspect_runtime_state.py --help
python scripts/inspect_runtime_state.py \
  --database /absolute/private/runtime.sqlite3 --capacity 100000 --timeout-seconds 2
```

The container includes the same standalone command at
`/app/scripts/inspect_runtime_state.py`. After deployment, an authorized
operator with private API connectivity and pod exec permission can run:

```bash
kubectl -n seed-mcp exec seed-mcp-seed-mcp-0 -c app -- \
  /app/.venv/bin/python /app/scripts/inspect_runtime_state.py \
  --database /app/.artifacts/runtime.sqlite3 --capacity 100000 --timeout-seconds 2
```

The example assumes namespace/release `seed-mcp`. Select the actual namespace,
pod and configured capacity deliberately. No shell, environment dump, Secret
read or extra writer is required.

Supply the deployment's actual `STATE_MAX_RECORDS`, not a guessed capacity.
The timeout defaults to 2 seconds and must be finite, positive and at most 30.
Missing/corrupt/schema-mismatched databases fail with fixed JSON errors and
are never created. Queries use SQLite read-only/query-only mode, a bounded
busy/query timeout and one consistent transaction.

Output contains only `schema_version`, `capacity`, table row counts and
capacity ratios, `submission_states`, `budget_states`, and
`oldest_unresolved_age_seconds` (null when none). Age is measured from the
oldest unresolved claim's creation, not when its state changed. Capacity
ratios apply independently to task ownership, budget reservations and HTTP
submission claims. No IDs, tenant/owner hashes, receipts, prompts, URLs,
credentials or raw errors are emitted. This does not report in-flight worker
counts; there is no MCP worker queue.

At high utilization, review claim growth, disk headroom and future row-cap
requirements before admitting new work. Claims never auto-prune. Raising a
cap needs a reviewed capacity decision; adding nodes does not raise SQLite
capacity or permit replicas. Never reset state, delete claims, requeue,
mark running submissions unresolved or blindly restore an older backup.
Unresolved work requires provider-side reconciliation, not database edits.
See [backup and recovery](byteplus-terraform.md#backup-upgrade-and-recovery).
