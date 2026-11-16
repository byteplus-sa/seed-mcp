### Accepted Tasks and Errors

Successful single calls, variation batches and dry runs use the output schema
below. A single-call failure remains error `ToolResult` text with any known
accepted task ID and diagnostic request ID, not structured success output.
Keep those IDs even when `isError=true`.

In a variation result, `task_id` and `error` can coexist after an accepted task's
ownership-record failure. `submitted` counts known accepted IDs, while
`failed` counts entries with errors. These counts can overlap: two accepted IDs
with one ownership-record error give `submitted=2` and `failed=1`.

Only accepted ownership-record failures become outward `AcceptedTaskError`
failures, which retain task/request IDs and are ambiguous/nonretryable.
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
