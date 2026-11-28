---
title: Troubleshooting
description: Quick fixes for hosted connection, generation and download problems.
---

| Problem | What to do |
| --- | --- |
| Cannot connect | Check the HTTPS URL ends in `/mcp`, remote Streamable HTTP is selected, and the connection is approved |
| Discovery works, generation fails | Check private header mappings and provider account access; discovery does not validate keys |
| `CREDENTIAL_REUSE` | Generate an independent client secret; do not reuse a provider key |
| `ENDPOINT_NOT_CONFIGURED` | Ask the operator to verify the exact model binding; do not guess IDs |
| Unsupported model or options | Use discovery and that model's limits; correct the request before resubmitting |
| TTS is missing | Refresh the tool list and check the server version; see [available tools](capabilities.md) |
| Local file tools are missing | These remain stdio-only |
| Rate or concurrency limit | Reduce parallel requests; distinguish rejected attempts from accepted work |
| TLS certificate error | Check your network or corporate trust configuration; never disable certificate verification |

<span id="http-configuration-check"></span>
<span id="http-authentication-fails"></span>
<span id="missing-provider-tools"></span>
<span id="unknown-tool-over-http"></span>
<span id="ssl-certificate-errors"></span>

Use [connection checks](connection-checks.md) to inspect header presence and
image/video bindings without a paid call. Never paste keys, complete client
configuration, or unredacted logs into chat.

<span id="timeout-on-long-generations"></span>
<span id="client-timeouts-vs-provider-latency"></span>

## A Request Timed Out

A timeout does not mean generation failed. Keep accepted task/request IDs.
For video, resume polling the existing task. Do not submit the same prompt
again just to check progress; it can create another charge.
Use a 660-second client timeout. See [recovery rules](calling-tools.md#timeouts-and-retries).

<span id="seedance-task-states"></span>

## Video Is Still Queued

Continue polling the same task ID. The provider gives no queue position or
reliable ETA. `queued` and `running` are not failures. A terminal failure
includes an error; review it before approving another generation.

<span id="provider-url-expired"></span>

## A Download Link Expired

Image/video links last about 24 hours; audio links about two hours.
The hosted service does not keep a durable copy. Check downloads you already
saved before considering another paid generation.

## Request Help

Provide the tool name, error code, time and a safe task/request ID when
available. Do not include provider keys, client secrets or signed media URLs.
