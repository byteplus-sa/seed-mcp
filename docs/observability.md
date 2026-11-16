# Observability

The server ships structured JSON logging and internal Prometheus metrics.
The `/metrics` endpoint is unavailable on HTTP; it is not a public monitoring
surface. HTTP `/health` and `/ready` expose minimal state without provider probes.
Provider HTTP calls also emit OpenTelemetry spans, but the server does not
configure an OTel exporter — spans are no-ops unless you wire up an SDK.

## Structured logging (`observability/logger.py`)

- **Output:** one JSON object per line, written to **stderr**. stdout is
  reserved for MCP JSON-RPC (stdio transport requirement).
- **Serialization:** `json.dumps(record, default=str, ensure_ascii=False)`.
  `default=str` stringifies non-JSON-native objects (UUIDs, datetimes,
  exceptions, dataclasses).

Each log line always contains:

| Field | Value |
|---|---|
| `ts` | `datetime.now(UTC).isoformat()` |
| `level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `msg` | human message |

plus any additional `**fields` passed to the helper (after redaction).

### Public API

Four module-level functions, all `(message: str, **fields: Any) -> None`:
`debug`, `info`, `warning` (emits level `"WARNING"`), `error`.

### Level control

| Env var | Default | Notes |
|---|---|---|
| `ARK_LOG_LEVEL` | `INFO` | recognized: `DEBUG`, `INFO`, `WARNING`, `ERROR`; an unknown value silently falls back to `INFO` |

`set_level(level)` overrides at runtime (called once from `create_server`,
which passes the resolved `Settings.log_level`); `get_level()` returns the
current name. `set_level` normalizes via `.upper()` (it does not trim
whitespace) and **raises `ValueError`** for unrecognized levels — it does
not fall back. The silent fallback to `INFO` happens only at module-import
time, where `ARK_LOG_LEVEL` is looked up in the level map with a
default of `20` (INFO).

Through the normal `Settings` path, `ARK_LOG_LEVEL` is a
`Literal["DEBUG","INFO","WARNING","ERROR"]` field with a before-validator
that uppercases; an untrimmed value such as `" info "` becomes `" INFO "`
and is rejected by Pydantic before `set_level` is ever called.

At default `INFO` (20): DEBUG is dropped; INFO/WARNING/ERROR are emitted.

### Redaction

`_redact` recursively walks dicts/lists. Any dict whose key (lowercased) is
in the redaction set is replaced with `"[REDACTED]"`. Redaction is **exact
key match**, not substring — so `user_url_custom` is NOT redacted.

Redacted keys (case-insensitive): `authorization`, `x-api-key`, `api_key`,
`apikey`, `token`, `secret`, `password`, `b64_json`, `audio_data`,
`image_data`, `base64`, `prompt`, `text_prompt`, `variation_prompts`,
`subtitle`, `subtitles`, `url`, `media_url`, `audio_url`, `image_url`,
`video_url`, `subtitle_text`.

The BYOK provider headers, client secret and operator HMAC key are sensitive
too. Live request secret echoes, including URL-encoded forms, are redacted.
Do not log raw exceptions, request headers or provider URLs.

Policy (per the module docstring): never log prompt text, full media URLs,
Base64, subtitles, or credentials. Redaction is a safety net; call sites
avoid passing these fields in the first place.

Generation and polling logs contain safe lifecycle metadata, not source/output
URLs or credentials. Provider success does not imply successful artifact
storage. Monitor `ArtifactRef.persistence_error` for Seedream/Seed Audio
fallbacks, `outputs[].persistence_issue` with `outputs[].persistence` for
Seedance, and top-level `persistence_issue` with `persistence` for OmniHuman.
These are distinct result shapes; successful MCP/provider metrics alone do
not prove that output was stored.

### Finalization and validation

`billed_provider_slot` logs commit/release exceptions as `ERROR` event
`budget_finalization_failed` with safe `provider`, `action` (`commit` or
`release`) and `reservation_id` fields, never raw exception text. These events
do not replace the provider result/error, raise `AcceptedTaskError`, or add to
Seedance's `failed` count. Failed finalization leaves conservative reserved
allowance; monitor the event and ledger rather than treating it as a new
provider failure. Reservation before dispatch still fails closed. Cancellation
cleanup is shielded best effort, not a guarantee that no reserved rows remain.

Seedance and OmniHuman share `record_accepted_task`. An accepted task's
ownership-record failure logs `ownership_record_failed` and surfaces an
ambiguous/nonretryable `AcceptedTaskError` retaining task/request IDs.
Seedance's `submitted` and `failed` counts can overlap for these ownership
errors, not for budget-finalization log events.

Understanding JSON Schema validation is offline: `$ref`, `$dynamicRef` and
`$recursiveRef` must be fragment-only (`#...`), and external schemas are never
retrieved. Nonlocal references are rejected before dispatch; unresolved
references during answer validation become `schema_violation` diagnostics
without discarding the billed completion. `understanding_schema_violation`
and `understanding_schema_violation_retry` describe answer validation, not a
provider transport failure or permission to blindly replay a request.

## Prometheus metrics (`observability/metrics.py`)

Nine metrics total — 6 Counters + 3 Histograms. **There are no Gauges.**
Label cardinality is intentionally bounded (no tenant, model, URL, or request
labels). All Histograms use the `prometheus_client` default buckets
`(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, +Inf)` seconds.

| Metric | Type | Labels | What it measures | Label values |
|---|---|---|---|---|
| `ark_mcp_tool_requests_total` | Counter | `tool`, `status` | Foreground outcomes, background acceptance, and worker outcomes | `accepted`, `success`, `error`, `exception`, `cancelled` |
| `ark_mcp_tool_duration_seconds` | Histogram | `tool` | Foreground execution or background worker execution duration, including failure and cancellation | — |
| `ark_mcp_tool_admission_duration_seconds` | Histogram | `tool` | Background task admission duration, including rejected submissions and excluding worker execution | — |
| `ark_mcp_background_job_submissions_total` | Counter | `target`, `status`, `path` | Allowlisted background-job admission by target and native or compatibility entry path | `status` = `accepted` / `rejected`; `path` = `native` / `compatibility` |
| `ark_mcp_provider_requests_total` | Counter | `provider`, `operation`, `status` | outbound provider HTTP requests | `operation` = HTTP method lowercased; `status` = `success` (HTTP < 400) / `error` (HTTP ≥ 400) / `exception` |
| `ark_mcp_provider_duration_seconds` | Histogram | `provider`, `operation` | provider HTTP request duration (observed in `finally`) | `operation` = HTTP method lowercased |
| `ark_mcp_artifact_operations_total` | Counter | `operation`, `status`, `media_type` | artifact store put/get | `operation` = `put` / `get`; only `status="success"` is emitted in current call sites |
| `ark_mcp_budget_rejections_total` | Counter | `product` | requests rejected for exceeding daily budget | one inc per rejection |
| `ark_mcp_retry_attempts_total` | Counter | `provider`, `operation` | retried provider attempts (excluding the initial attempt) | one inc per retry |

> **Upgrading dashboards to 0.2.0.** The `tool` label on
> `ark_mcp_tool_requests_total`, `ark_mcp_tool_duration_seconds`, and
> `ark_mcp_tool_admission_duration_seconds` (and the `target` label on
> `ark_mcp_background_job_submissions_total`) carries the 0.2.0 tool names.
> Panels and alerts keyed on removed 0.1.x names (for example the per-family
> Seedance create tools or the per-product task pollers) stop receiving data;
> switch them to the replacements listed in
> [Migrating to 0.2.0](migration-0.2.md).
> The merged `seedance_create_task` does not separate Seedance 2.0, regular 2.5,
> and 2.5 Flash by label, and metrics carry no model label. To split by model,
> use the `model` field in the structured logs: `seedance_task_created` (and
> `seedance_create_task_complete`) for a single task, and
> `seedance_variations_complete` for a variations call.

Retry metrics describe actual provider retry attempts, not permission to repeat
a billable submission. An ambiguous outcome must be reconciled; read-only
task polling can retry provider-marked retryable failures such as HTTP 429.

### `MetricsMiddleware`

**Admission and execution are measured separately.** `MetricsMiddleware`
intercepts `on_call_tool`; it does not intercept task polling, resource reads,
list-tools, or HTTP routes. Foreground calls retain their existing outcome
counter and execution histogram. Native background submissions observe
`TOOL_ADMISSION_DURATION`; accepted submissions increment
`TOOL_REQUESTS{status="accepted"}`, while failed admission increments the
submission counter with `status="rejected"`.

Registered handlers use `instrument_tool_execution` to measure execution in
real task workers. Each handler execution records its terminal outcome and
`TOOL_DURATION`, including elapsed time when an exception or cancellation
interrupts the handler. Foreground execution bypasses this wrapper's metrics
so middleware counts it exactly once. Repeated `tasks/get` polling does not
add execution measurements.

`ark_mcp_background_job_submissions_total` separates native task admission from
ordinary `ark_job_submit` admission without labeling job IDs, principals,
prompts, or URLs. Its `target` values come only from the immutable background
tool registry. Unknown target strings are deliberately not emitted as labels.

The `tool` labels on request, execution-duration and admission-duration metrics
are catalog names or the fixed value `unknown`. Arbitrary unknown tool names
collapse to `unknown` in both middleware and worker instrumentation; they never
create one retained series per caller-supplied name. This differs from unknown
background `target` values, which are skipped entirely.

`success` means a returned value without an MCP error, `error` means a returned
`ToolResult` with `is_error=True`, `exception` means a raised Python exception,
and `cancelled` means an executing handler was interrupted by cancellation.
These are MCP/handler outcomes, not provider HTTP statuses. A background task
normally produces both an `accepted` sample and one terminal sample; exclude
`accepted` when calculating execution error rates. A task cancelled before its
handler starts has no execution sample. Abrupt worker termination cannot emit
terminal metrics; a replayed worker attempt emits its own execution sample.

### `/metrics` endpoint

HTTP does not register this route. Internal counters remain useful to tests
and approved operator instrumentation but are not publicly exposed.
Background admission/execution metrics above apply only to local stdio,
where jobs/native tasks remain supported.

## OpenTelemetry / tracing

Spans are emitted around provider HTTP requests in `providers/base.py`:

```python
with get_tracer().start_as_current_span(
    f"provider.{self.PROVIDER}.{operation}",
    record_exception=False,
    set_status_on_exception=False,
) as span:
    span.set_attribute("provider.name", self.PROVIDER)
    span.set_attribute("http.request.method", method)
    ...
    span.set_attribute("http.response.status_code", response.status_code)  # success path only
```

- **Span name:** `provider.<provider>.<operation>` (e.g.
  `provider.modelark.post`, `provider.seed_speech.post`).
- **Attributes:** `provider.name`, `http.request.method`, and
  `http.response.status_code` (success path only). On exception,
  a sanitized generic exception records the event; raw exception text is not used.
- **Scope:** spans exist **only** around provider HTTP calls through
  `BaseHttpGateway._request`. There are no spans around tool execution,
  artifact store ops, budget reservation, the retry loop, resource reads, or
  the HTTP routes.

> **No exporter configured.** `get_tracer()` returns FastMCP's tracer, which
> is a **no-op unless the operator initializes the OpenTelemetry SDK** (e.g.
> sets `OTEL_TRACES_EXPORTER`, `OTEL_EXPORTER_OTLP_ENDPOINT`, etc. in the
> process environment). By default the span calls execute but produce no
> exported telemetry. Wire up OTel export yourself to get spans out.

## Gaps worth knowing

- No Gauges anywhere — in-flight requests, current daily spend, stored
  artifact count, and concurrency depth are not metricated (spend is only
  observable via the SQLite ledger; in-flight only via the process metrics).
- `ARTIFACT_OPERATIONS` has a `status` label, but call sites only ever emit
  `success` (failures raise before the counter is touched).
- HTTP `/metrics` is unavailable. Anonymous `/health` and `/ready` return
  minimal process/state status, not credentials or provider readiness.

See [configuration.md](configuration.md) for the related env vars and
[deployment.md](deployment.md) for probe/monitoring guidance.
