---
title: Connection Checks
description: Check discovery and private-header configuration without generating media.
---

## Verify

After [connecting your client](setup/install.md), ask:

```text
Use only ark-seed. List its tools and call ark_list_models with {"input": {}}.
Report the available services and models. Do not generate or upload.
```

Expect eight tools and `connection=null`. This confirms discovery, not
provider-key validity or account entitlement.

## Optional Image/Video Configuration Check

After configuring private headers, ask:

```text
Call ark_list_models with {"input":{"check_connection":true}}.
Report missing headers or model bindings. Do not generate or upload.
```

Omit `kind` to check both image and video. This HTTP-only check makes no provider
calls and does not check Seed Speech credentials.

| Result | Action |
| --- | --- |
| `missing_modelark_key` | Check the private `X-ModelArk-Api-Key` mapping |
| `missing_client_secret` | Check the independent `X-MCP-Client-Secret` mapping |
| `endpoint_not_configured` | Ask the operator to verify and bind the exact model/endpoint |
| `configuration_valid=true` | Headers and bindings are configured, not authenticated |
| `authentication_verified=false`, `provider_calls_made=false` | Expected: no provider was contacted |

Malformed headers can be rejected before a result is returned. Never share
secret values or full client configuration while diagnosing a connection.

<span id="connect"></span>

## Custom Model Defaults

Most users should leave endpoint headers unset. If the operator supplies a
verified binding, `X-ModelArk-Seedream-Endpoint` or
`X-ModelArk-Seedance-Endpoint` can select that default. Explicit tool `model`
wins. Unknown IDs are not echoed; do not guess their model family or send
AK/SK credentials to this server.

<span id="generate-a-client-snippet"></span>

For advanced integrations, the repository contains a
[client snippet generator](../scripts/configure_http_client.py).
It is optional; the [connection guide](setup/install.md#clients) already has
ready-to-use templates. More help: [Troubleshooting](help.md).
