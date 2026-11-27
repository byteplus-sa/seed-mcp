# Runtime Services

The server lifespan owns one `RuntimeServices` instance, accessed by tools
through `get_runtime(ctx)`. HTTP is database-free and uses provider-key task
authorization. Local stdio retains SQLite-backed artifacts and bookkeeping.
Both transports execute ordinary calls directly, without MCP jobs or native tasks.

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

`STATE_BACKEND` resolves automatically to `none` for HTTP and `sqlite` for
stdio; an incompatible explicit value rejects startup. HTTP never opens
SQLite, PostgreSQL, Redis, a state directory or a filesystem lease.

Local stdio uses `<artifact_dir>/runtime.sqlite3` for task/object-key ownership,
the budget ledger and artifact cache. Connections use WAL mode and serialized
worker-thread queries. `sqlite_io.drain_task` drains worker completion before
releasing locks or propagating cancellation, including repeated cancellation.
These local stores are single-process only, not shared state for HTTP replicas.

Task get/list/cancel and Draft lookup are authorized by the supplied provider
key. `X-MCP-Client-Secret` separates per-pod admission scopes, not task access.
Clients sharing a provider key can access whatever that key authorizes.
Use separate provider credentials when independent authorization is required.

Omit `idempotency_key`; the retained legacy field is rejected when supplied.
An identical create is a new operation and may bill again. Save task/request IDs,
poll existing tasks, and reconcile lost or uncertain create responses through
the provider. Never automatically retry an uncertain mutation.

Rate limits and in-flight/provider/principal concurrency are in-memory per pod;
they multiply with replicas and reset at restart. `DAILY_BUDGET_USD` must be `0`
on HTTP; use provider-side spend controls. Readiness is lifespan-only and makes
no storage or provider probes. No database, migration, distributed lock, shared
volume or sticky session is needed for the hosted deployment.

## `RuntimeServices` fields

| Field | HTTP | Local stdio |
| --- | --- | --- |
| `settings` | Request server configuration | Startup configuration |
| `safe_downloader` | Runtime-owned downloader; persistence remains disabled | Downloads generated media when requested |
| `artifact_store` | `DisabledArtifactStore` | `FilesystemArtifactStore` |
| `ownership_store` | `ProviderAuthorizedTasks`, no retained IDs or local authorization | `SQLiteTaskOwnershipStore` |
| `object_key_ownership_store` | Disabled | SQLite-backed local object-key ownership |
| `budget_ledger` | `None` | `BudgetLedger` |
| `provider_limiters` | Per-pod provider/principal admission | Per-process provider admission |
| `task_artifact_cache` | Disabled | `SQLiteTaskArtifactCache` |
| `task_artifact_locks` | Unused for persistence | Process-local persistence lock registry |
| `metrics_listener` | Optional loopback listener | `None` |

HTTP never invokes `build_state_stores`. Runtime cleanup closes owned services
and drains through repeated cancellation, reusing the same close task.

## Concurrency limiters (`ProviderLimiters`)

Two per-pod layers, acquired owner-first for billable calls:

- **Provider-level** — one global `asyncio.Semaphore` per provider bucket:
  `"modelark"`, `"seed-speech"`, `"tos"`, and `"s3"`.
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
| Local SQLite lock wait | `busy_timeout=5000` ms | `runtime.py::_open_sqlite_connection` | A blocked stdio writer waits up to 5 s in its worker thread, never on the event loop |
| HTTP request body | `MCP_HTTP_MAX_BODY_BYTES=2097152` (2 MiB) | `config/env.py` | Positive streamed body cap |
| HTTP admission | `MCP_HTTP_MAX_IN_FLIGHT=64`, `RATE_LIMIT_RPM=60` | `security/http_middleware.py` | Positive per-pod in-flight bound and per-IP rate bound (per pod), including discovery |
| Local stdio state | `STATE_MAX_RECORDS=100000` | `runtime.py` | Local record capacity only; HTTP has no ledger |
| Variation batch | `variation_batch_deadline(...)` | `tools/_parallel.py` | See [Parallel variations](#parallel-variations-tools_parallelpy) |

- **Use client timeout 660 seconds** with the default 600-second tool deadline,
  and compatible proxy timeouts. The tool timer starts after MCP parsing,
  before credentials, bindings, admission and execution.
- **Cancellation is cooperative.** SQLite and SDK threads drain before locks,
  slots or clients are released, including repeated cancellation. Cleanup can
  exceed the nominal deadline; it is not a hard kill or provider cancellation.
- `TOOL_DEADLINE_EXCEEDED` is text-only, preserving possible mutation and known
  safe accepted IDs. Pre-dispatch/read-only expiry does not claim billed work
  began. External cancellation propagates; inner provider timeouts retain
  their normalized errors. Never blindly resubmit after a lost response.
- ModelArk polling and discovery do not wait on saturated generation slots.
  They remain subject to per-pod HTTP in-flight/body bounds and per-IP rate
  limits (per pod).
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

This persistence coordination is local stdio only. HTTP rejects persistence
and never enters the artifact-cache or single-flight path.

## Daily budget + cost estimation

### Budget ledger (`BudgetLedger`)

Local stdio SQLite uses the same file as local ownership. HTTP never opens this ledger:

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

The local daily window is the UTC calendar date, scoped per
`(principal_id, tenant_id)`. Estimates are not an account-wide spending ceiling.
HTTP requires a zero budget setting and performs no reservations or accounting;
use provider-side spend controls.

### Cost estimation (`tools/_cost.py`)

The estimator behind the daily budget and cost log uses built-in heuristics
only. Discovery returns no pricing fields, and no operator-account price
refresher runs. `price_source` is `builtin`. Estimates are not provider
quotes, settlement amounts or guarantees of an actual spend ceiling.

**Built-in rates:**

| Constant | Value |
|---|---|
| `COST_PER_IMAGE` | `0.03` USD (families other than Seedream 5.5) |
| `SEEDREAM_5_5_OUTPUT_TIERS` | `0.020` / `0.035` / `0.079` USD per output image, by pixel count |
| `COST_PER_SEEDREAM_5_5_INPUT_IMAGE` | `0.008` USD per input image per call |
| `COST_PER_AUDIO_SECOND` | `0.0031` USD |
| `COST_PER_VIDEO_TASK` | `0.07` USD (`0.35` for Seedance 2.5) |
| `DEFAULT_MAX_CONCURRENT` | `5` |

`estimate_cost(product, variations, ..., model_id=None)`:

| `product` | Formula |
|---|---|
| `"image"` | 5.5: `round(variations * (output_rate + reference_images * 0.008), 4)`; other families: `round(variations * 0.03, 4)` |
| `"audio"` | `round(variations * max(duration_seconds, 10) * 0.0031, 2)` — **floor of 10 seconds per variation** |
| `"video"` | `round(variations * 0.07, 2)`; regular 2.5 and Flash use `0.35` per task, selected by registry family; a registered model-specific override wins |
| (any other) | `0.0` |

Seedream 5.5 output estimates use the supplied high-resolution pricing table:
at most 2.61M pixels costs $0.020; above 2.61M through 4.63M costs $0.035;
above 4.63M through the exact 8,294,400-pixel limit costs $0.079.
These are rounded pricing thresholds, not additional size-validation limits.
Named `1K`/`1.5K` use the lower tier; `2K` and omitted size use the middle tier.
Custom dimensions select the tier by width times height. Each variation repeats
the input-image charge: two UHD outputs with one reference estimate $0.174.
The resolved `seedream_5_5` family selects these rates even on a custom endpoint;
model-ID text alone does not select pricing.

Dry runs, dispatch logging and local budget reservations use the same estimate.
`price_source` remains `builtin`: this is not live account pricing or a billing
quote. Source: the operator-supplied 261028 high-resolution table received
2026-11-27; see [model contract notes](models.md#image-capabilities-imagecapabilities).

Video estimates do not account for resolution or duration. Flash uses the
static 2.5 per-task estimate, not its token-based provider price.

## Provider task ownership (`SQLiteTaskOwnershipStore`)

Local stdio records asynchronous provider task IDs and rejects recorded owner
mismatches. HTTP does not instantiate this store; its task access is delegated
to the selected provider credential. Local schema:

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
| `ping()` | Local `SELECT 1` liveness check; HTTP readiness never calls it. |
| `close()` | closes the connection. |

Every lookup is scoped by `provider`, `tenant_id` and `task_id`; owner listings also require
`principal_id`. The `is_local` shortcut only affects the
missing-row branch — a row that exists and belongs to someone else still raises,
even in local mode.

> This is distinct from **artifact ownership**, which is stored in
> `.meta.json` sidecars next to the artifact bytes
> (`artifacts/filesystem_store.py`). See [artifacts.md](artifacts.md).

## HTTP Submission Journal

Removed. There is no durable deduplication or saved-response replay.
`seedance_create_task` retains a nullable legacy
`idempotency_key` schema field but rejects non-null values on both transports,
including dry runs. Every repeated create is independent and may bill again.
See [HTTP submission safety](../specs/SPEC_HOSTED_BYOK.md#http-submission-safety).

## Persistence cache

On local stdio, `RuntimeServices.task_artifact_cache` is a `SQLiteTaskArtifactCache` backed by
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

Uncertain mutation transport failures and malformed mutation 2xx responses
are ambiguous/nonretryable. Demonstrably pre-dispatch connection/pool failures
remain eligible for bounded retries. Diagnostics omit raw exceptions,
credentials and credential-bearing URLs. Provider retries do not provide
idempotency or exactly-once billing.

## Billable call composition (`billed_provider_slot`)

HTTP acquires per-pod admission and directly calls the provider without budget
reservations. Local stdio reserves budget after admission:

| Local outcome | Budget action |
| --- | --- |
| Success, ambiguous provider error or provider timeout | Commit |
| Other provider error or unexpected exception | Release |
| Cancellation after that slot dispatched a mutation | Commit |
| Cancellation before dispatch | Release any reservation |
| Cancellation during reservation | Drain reservation, release if known, never dispatch |

Finalization errors leave conservative reserved allowance and log only safe
fields. They do not replace the provider result/error or trigger resubmission.
Cancellation drains local bookkeeping before admission is released.

Seedance captures safe accepted IDs inside the slot, before the
next await. HTTP receipts must match `[A-Za-z0-9._:-]{1,256}` and must not echo
request/operator secrets. Unsafe IDs produce ambiguous, nonretryable
`UNSAFE_TASK_RECEIPT` without echoing them. Safe IDs remain only in the live call
for deadline diagnostics. Stdio additionally drains ownership recording; a
recording failure retains accepted IDs in an `AcceptedTaskError`.

## Error taxonomy

| Class | Module | Raised by | Meaning |
|---|---|---|---|
| `ProviderError` | `domain/errors.py` | provider gateways + transport normalizers | wraps a `NormalizedProviderError`; the single retryable error type |
| `AcceptedTaskError` | `domain/errors.py` (extends `ProviderError`) | `record_accepted_task` | local accepted-task ownership recording failed; retains task/request IDs, ambiguous and nonretryable |
| `BudgetExceededError` | `runtime.py` (extends `ValueError`) | `BudgetLedger.reserve` | daily budget would be exceeded; raised before dispatch |
| `ValueError` | builtin | `ProviderLimiters`, `RetryPolicy`, `resolve_prompts` | config/argument validation |
| `RuntimeError` | builtin | `get_runtime`, `BudgetLedger.reserve` | missing runtime services / reservation ID |
| `PermissionError` | builtin | `get_principal`, `require_owner` | missing token, missing principal/tenant claims, ownership mismatch |

`NormalizedProviderError` carries: `provider` (including `modelark`, `seed-speech`,
`tos` and `s3`),
`operation`, `http_status`, `code`, `message`, `request_id`, `retryable`,
`ambiguous_completion`, `retry_after_seconds`. Transport-layer normalizers in
`BaseHttpGateway` follow the table below.

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
| Mutation | Seedance create, cancel, delete; Seedream/Seed Audio generate | `retryable=False`, `ambiguous_completion=True` | No — reconcile by task/request ID |
| Read-only poll | Seedance `get_task` / `list_tasks` | `retryable=True`, `ambiguous_completion=False` | Yes |

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
from those entries: an accepted task with a local ownership-record error counts
in both. Budget-finalization log events do not add failures to these counters.

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

`before_provider_request(side_effect=...)` checks expiry before dispatch.
`record_accepted_receipt` retains safe IDs; `runtime.capture_accepted_task`
validates HTTP receipts before capture. The wrapper rechecks expiry when a
handler suppresses cancellation. Neither transport accepts explicit
`io.modelcontextprotocol/tasks` opt-in.

## HTTP Readiness and Recovery

HTTP `/health` and `/ready` expose minimal process/lifespan status and never
probe storage or providers. Caddy exposes `/mcp` and `/health` only; `/ready`
remains an internal loopback exec probe. The main app has no `/metrics` route.
`MCP_METRICS_PORT=0` disables the optional separate loopback metrics listener.
See [private metrics access](observability.md#metrics-endpoint).

There is no hosted state to restore or replay. Restarting a pod does not
cancel provider work; clients must retain IDs and poll with authorized provider
credentials. A lost create response may hide billed work and must be reconciled,
not resubmitted automatically.

This is a fresh stateless deployment. Historical database compatibility and
stateful-release migration tooling are not part of this repository.
