### HTTP Configuration Check

The ordinary example above keeps `check_connection=false`: discovery is
static/anonymous and returns `connection=null` without inspecting credentials.
To opt in over live HTTP, call:

```json
{
  "name": "ark_list_models",
  "arguments": {
    "input": {
      "check_connection": true
    }
  }
}
```

Omitted `kind` checks both video and image; `"image"` or `"video"` checks only
that route. Other kinds are rejected, as are stdio calls
and calls without a live HTTP request context. No other provider is checked.

| Result | Interpretation |
| --- | --- |
| `configuration_valid` | Both required headers present and all checked defaults exactly bound |
| `modelark_key_present`, `client_secret_present` | Presence of live headers only; missing headers appear in `issues` |
| `authentication_verified`, `provider_calls_made` | Always false; no upstream authentication or metadata request |
| `routes[].source` | `request_header` or `server_default` |
| `routes[].configured` | Exact selection is in that product's registry |
| `routes[].model_id`, `routes[].family` | Configured ID/family, or null when unknown; unknown values are not echoed |
| `routes[].issue` | `endpoint_not_configured` requires operator verification/binding, otherwise null |

`issues` contains `missing_modelark_key` and/or `missing_client_secret`.
Malformed headers can fail HTTP validation before this diagnostic result.
A valid configuration does not prove endpoint existence, current lineage,
activation, permissions, balance or reachability. Explicit create-tool `model`
wins over endpoint headers; `models[].is_default` remains the server default.
The Seedream example elsewhere explicitly selects 5.5, so omit that `model`
when you intend to use an operator-verified image endpoint default.

Use the [setup check table](/seed-mcp/setup/shared-server/#optional-imagevideo-configuration-check)
for remediation and the
[BYOE authority contract](https://github.com/byteplus-sa/seed-mcp/blob/main/specs/SPEC_HOSTED_BYOK.md#byoe-endpoint-authority)
for the GetEndpoint AK/SK boundary. No arbitrary endpoint self-service,
provider authentication or paid validation is performed by discovery.
