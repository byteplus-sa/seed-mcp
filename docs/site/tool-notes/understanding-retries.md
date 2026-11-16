### Completion Retry Safety

Understanding is billable inference, not a read-only task poll. A timeout
after possible dispatch returns `retryable=false` and `ambiguous_completion=true`.
Lost responses, read/write/protocol failures and malformed provider 2xx responses
are also ambiguous/nonretryable: completion may already have consumed tokens.
Reconcile by request ID when available; never blindly repeat the completion.

Chat/mutation 5xx responses are ambiguous and never automatically retried, even
when HTTP normalization marks them `retryable=true`. Eligible 429 rejections
and demonstrably pre-dispatch connection failures can receive bounded retries.
Understanding disables all `TIMEOUT` retries, including connect/pool timeouts.

Explicit `json_retry` adds billed attempts for JSON validation of a received
answer; it does not retry a lost or malformed provider response. See the
[runtime retry policy](/ark-mcp/runtime/#retry-policy-providersretrypy).
