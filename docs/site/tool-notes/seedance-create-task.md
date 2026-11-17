### Accepted Tasks and Errors

Successful single calls, variation batches and dry runs use the output schema
below. A single-call failure remains error `ToolResult` text with any known
accepted task ID and diagnostic request ID, not structured success output.
Keep those IDs even when `isError=true`.

In a variation result, `task_id` and `error` can coexist after an accepted task's
journal/ownership-record failure. `submitted` counts known accepted IDs, while
`failed` counts entries with errors. These counts can overlap: two accepted IDs
with one ownership-record error give `submitted=2` and `failed=1`.

Accepted journal/ownership-record failures become outward `AcceptedTaskError`
failures, which retain task/request IDs and are ambiguous/nonretryable.
On HTTP, safe accepted IDs are journaled before ownership; a journal failure
still attempts ownership. Unsafe or secret-echoing IDs are rejected before
either write and never echoed.
Budget-finalization exceptions log `ERROR` event `budget_finalization_failed`
without replacing the provider result/error or adding to `failed`. Failed
commit/release leaves conservative reserved allowance. Reservation before dispatch
still fails closed; cancellation cleanup is shielded best effort, not a guarantee
that no reserved rows remain.

Never resubmit accepted tasks. On HTTP, MCP polling requires recorded ownership;
if recording failed, reconcile directly with the provider using task/request IDs.
Trusted stdio permits unrecorded IDs, but still rejects a recorded owner mismatch.
A null `task_id` can mean unknown acceptance, not proof that nothing was billed.
See [retry and recovery guidance](/ark-mcp/runtime/#retry-policy-providersretrypy).

A single HTTP key covers the whole variation batch. Only fully successful
saved receipts replay; partial batches remain unresolved with known IDs and
are never automatically resumed. Repeat identical arguments/key for delivery
recovery, not polling; never change keys to bypass uncertain acceptance.
