### Accepted Tasks and Errors

Successful single calls, variation batches and dry runs use the output schema
below. A single-call failure remains error `ToolResult` text with any known
accepted task ID and diagnostic request ID, not structured success output.
Keep those IDs even when `isError=true`.

In a variation result, `task_id` and `error` can coexist after an accepted task's
local ownership-record failure. `submitted` counts known accepted IDs, while
`failed` counts entries with errors. These counts can overlap: two accepted IDs
with one ownership-record error give `submitted=2` and `failed=1`.

Local accepted-task ownership-record failures become outward `AcceptedTaskError`
failures, which retain task/request IDs and are ambiguous/nonretryable.
HTTP keeps safe accepted IDs only in the live invocation for deadline diagnostics,
without a journal or ownership ledger. Unsafe or secret-echoing IDs are rejected
and never echoed.
Local budget-finalization exceptions log `ERROR` event `budget_finalization_failed`
without replacing the provider result/error or adding to `failed`. Failed
commit/release leaves conservative reserved allowance. Reservation before dispatch
still fails closed; cancellation cleanup is shielded best effort, not a guarantee
that no reserved rows remain.

Never resubmit accepted tasks. HTTP polling uses provider-key authorization,
not client-secret ownership. Reconcile uncertain acceptance using task/request IDs.
Trusted stdio permits unrecorded IDs, but still rejects a recorded owner mismatch.
A null `task_id` can mean unknown acceptance, not proof that nothing was billed.
See [retry and recovery guidance](/seed-mcp/runtime/#retry-policy-providersretrypy).

Omit `idempotency_key`; supplied legacy keys are rejected on both transports.
There is no durable replay or automatic partial-batch resume. Repeated creates
may bill again; never automatically resubmit an uncertain create.
