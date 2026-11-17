# Observability

The server ships structured JSON logging and internal Prometheus metrics.
The main HTTP app has no `/metrics` route. Optional `MCP_METRICS_PORT` defaults
to `0` (off); when enabled, a separate HTTP-runtime listener binds only
127.0.0.1. It is not a public monitoring surface. Backend `/health` and `/ready`
expose minimal state without provider probes; VKE Caddy exposes only `/health`.
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
On HTTP, safe IDs are journaled before ownership. A journal-write failure
logs `submission_record_failed`, still attempts ownership, and surfaces
`SUBMISSION_RECORD_FAILED` with safe accepted IDs. Unsafe IDs are rejected
before either write without echoing them.
Seedance's `submitted` and `failed` counts can overlap for these journal/ownership
errors, not for budget-finalization log events.
`submission_finalization_failed` records only a safe action (`save_receipt`
or `mark_unresolved`), never raw errors or input. A receipt-write failure
preserves the first provider result but leaves repeat calls fail-closed.
See [HTTP submission recovery](runtime.md#http-submission-journal).

## Prometheus metrics (`observability/metrics.py`)

Nine application metrics: 7 Counters and 2 Histograms. **There are no application
Gauges.** The default Prometheus registry can also expose library/process metrics.
Label cardinality is intentionally bounded (no tenant, model, URL, or request
labels). All Histograms use the `prometheus_client` default buckets
`(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, +Inf)` seconds.

| Metric | Type | Labels | What it measures | Label values |
|---|---|---|---|---|
| `ark_mcp_tool_requests_total` | Counter | `tool`, `status` | Direct tool outcomes | `success`, `error`, `exception`, `cancelled` |
| `ark_mcp_tool_duration_seconds` | Histogram | `tool` | Direct call duration, including admission, execution and cancellation cleanup | — |
| `ark_mcp_provider_requests_total` | Counter | `provider`, `operation`, `status` | outbound provider HTTP requests | `operation` = HTTP method lowercased; `status` = `success` (HTTP < 400) / `error` (HTTP ≥ 400) / `exception` |
| `ark_mcp_provider_duration_seconds` | Histogram | `provider`, `operation` | provider HTTP request duration (observed in `finally`) | `operation` = HTTP method lowercased |
| `ark_mcp_artifact_operations_total` | Counter | `operation`, `status`, `media_type` | artifact store put/get | `operation` = `put` / `get`; only `status="success"` is emitted in current call sites |
| `ark_mcp_budget_rejections_total` | Counter | `product` | requests rejected for exceeding daily budget | one inc per rejection |
| `ark_mcp_retry_attempts_total` | Counter | `provider`, `operation` | retried provider attempts (excluding the initial attempt) | one inc per retry |
| `ark_mcp_admission_rejections_total` | Counter | `provider`, `reason` | Rejected owner/provider admission before dispatch of this attempt | `reason` = `capacity` or `timeout` |
| `ark_mcp_tool_deadlines_total` | Counter | `dispatch` | Cooperative deadline expiries, not provider cancellation | `mutation`, `read`, `none` |

> **Upgrading dashboards to 0.2.0.** The `tool` label on
> `ark_mcp_tool_requests_total` and `ark_mcp_tool_duration_seconds`
> carries the retained tool names. Removed job-admission metrics no longer emit.
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

`MetricsMiddleware` intercepts ordinary `on_call_tool` calls on both transports,
including provider polling tools. It does not count resource reads, list-tools
or HTTP routes. Each direct call records one terminal outcome and duration
in `finally`; there is no separate MCP job-admission or worker metric.

The `tool` labels are catalog names or the fixed value `unknown`. Arbitrary
unknown tool names never create one retained series per caller-supplied name.

`success` means a returned value without an MCP error, `error` means a returned
`ToolResult` with `is_error=True`, `exception` means a raised Python exception,
and `cancelled` means an executing handler was interrupted by cancellation.
These are MCP/handler outcomes, not provider HTTP statuses.
`TOOL_DEADLINE_EXCEEDED` returns an error result; external cancellation is
`cancelled`. SDK/SQLite draining may extend duration beyond the cooperative
deadline. A forced process termination cannot emit a terminal measurement.
Accepted provider IDs do not create a separate MCP `accepted` outcome.

### `/metrics` endpoint

The main HTTP app does not register this route. `MCP_METRICS_PORT=0` disables
the separate listener; otherwise it accepts ports 1024-65535 and binds only
127.0.0.1 for the HTTP runtime. Stdio never starts it. Its owned thread drains
on shutdown; unknown paths return 404 and access logging is disabled.
Direct-call metrics apply on both transports; neither has MCP jobs/native tasks.

VKE `app.metricsEnabled=true` selects private port 9000; the default is false.
No public or metrics Service exposes it, and Caddy rejects `/metrics`.
After separately authorized deployment, with private API connectivity and
pod port-forward RBAC, an operator can forward only onto workstation loopback:

```bash
kubectl -n seed-mcp port-forward --address 127.0.0.1 pod/seed-mcp-0 19000:9000
```

Use the actual namespace and pod name; the example assumes release `seed-mcp`.
In a second terminal, inspect `http://127.0.0.1:19000/metrics`, then stop the
forward when finished. Never use `--address 0.0.0.0`, a public ingress, or
customer credentials for monitoring.

For state pressure and unresolved ages, use the
[read-only aggregate inspector](runtime.md#read-only-state-inspection).
Neither counters nor inspection are a repair/requeue mechanism. Admission/
deadline labels contain no tenant/owner IDs, prompts, URLs or keys. HTTP
rate/body-limit events use bounded route labels, never arbitrary paths or
raw forwarding headers.

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

- No application Gauges: in-flight requests, current daily spend, stored
  artifact count, and concurrency depth are not metricated (spend is only
  observable via the SQLite ledger; in-flight only via the process metrics).
- `ARTIFACT_OPERATIONS` has a `status` label, but call sites only ever emit
  `success` (failures raise before the counter is touched).
- Public `/metrics` is unavailable. Private listener access requires explicit
  enablement and operator access. Backend `/health` and `/ready` return minimal
  process/state status, not credentials or provider readiness.

See [configuration.md](configuration.md) for the related env vars and
[deployment.md](deployment.md) for probe/monitoring guidance.
