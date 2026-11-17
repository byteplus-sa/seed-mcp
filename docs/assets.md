# Native Seedance Asset References

**Seedance accepts existing authorized `asset://<id>` references with the
normal ModelArk key.** This applies over stdio and HTTP BYOK;
no asset-management credential or feature flag is needed.

The server does not create, list, rename, delete or verify provider assets.
Obtain IDs and complete any required rights, consent and liveness procedures
through the provider console or another authorized administration workflow.
Never invent an asset ID or assume an ID proves consent or ownership.

## Supported Inputs

| Tool | Asset reference behavior |
|---|---|
| `seedance_create_task` | Passes native references in `images`, `videos` and `audios` to ModelArk |
| Seedream, Seed Audio and OmniHuman | Native provider asset references are not supported; use their documented HTTPS/Base64/artifact input forms |

The server validates the reference syntax and the selected model's request
limits. **It does not look up asset status, authorization, project membership
or media type before submission.** The provider decides whether the reference
is usable. Local schema validation and dry-run success do not prove provider
acceptance, and an invalid or unusable reference can fail after submission.
There is no asset-to-URL resolution fallback.

See [model limits](models.md) and the
[Seedance tool reference](/ark-mcp/tool-reference/seedance-create-task/).

## Submit And Poll

1. Obtain an authorized, usable ID from the provider workflow.
2. Discover the configured Seedance model and check its limits.
3. Call directly on either transport, referring to inputs by
   position, such as "Image 1" or "Video 1", not by asset ID.
4. Keep the provider task IDs and, on stdio, the Ark job ID.
5. Poll `gen_task_get` with `persist_output=false`, then persist completed
   output through a direct local poll or download the HTTP result URL.
   Never resubmit generation to poll.

This exact MCP job envelope is a non-billable local request preview:

```json
{
  "input": {
    "tool_name": "seedance_create_task",
    "arguments": {
      "input": {
        "prompt": "Image 1 walks through a softly lit studio.",
        "images": ["asset://asset-EXAMPLE"],
        "duration": 5,
        "resolution": "480p",
        "dry_run": true
      }
    }
  }
}
```

Replace the synthetic ID and remove `dry_run` only when deliberately approving
paid work. A provider-authorized AIGC image was accepted in earlier regular
Seedance 2.5 testing; that evidence does not establish every model, input
modality, account or current asset's availability.

## Uploads Are Different

Stdio-only `media_upload` stores ordinary reference files in TOS/S3 and returns
`object_key` plus a presigned HTTPS URL. It does not register a provider asset
or return an `asset://` ID. Use `media_presign` to renew those ordinary URLs.

HTTP uses the request's `X-ModelArk-Api-Key` and required `X-MCP-Client-Secret`,
including dry runs. Discovery is anonymous/static; HTTP has no storage/artifacts
or resources and keeps persistence false. It never falls back to operator keys.
See [security](security.md) and [direct execution](integration-guide.md).
