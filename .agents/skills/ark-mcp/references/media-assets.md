# Object storage and native assets

Behaviour and gotchas for `media_upload`, `media_presign`, and native Seedance asset references.
For parameters see the tool schema and
[API reference](https://github.com/byteplus-sa/seed-mcp/blob/main/docs/api-reference.md). Per-model limits:
[models-and-limits.md](models-and-limits.md); env vars:
[environment.md](environment.md); direct calls and provider polling:
[workflows.md](workflows.md), [polling-and-artifacts.md](polling-and-artifacts.md).

## Execution mode at a glance

The table is **stdio-only**. HTTP has no local upload/presign renewal,
job/native-task or artifact/resource surface. Host reference URLs externally
or use [managed Files](#managed-files) below with the user's ModelArk key.

| Tool | Mode | Needs |
|---|---|---|
| `media_upload` | direct | object storage (S3) |
| `media_presign` | direct | object storage |

Use a 660-second client timeout for the default 600-second cooperative tool
deadline. SDK threads drain before admission slots or clients are released,
so cancellation cleanup can exceed that deadline. Never blindly retry an
uncertain upload. See [local-output.md](local-output.md).

## Object storage (`media_upload`, `media_presign`)

For URL-only references (such as Seedance video/audio), S3 is an optional
local alternative to managed Files or an existing public HTTPS URL.

### `media_upload`

Uploads 1-50 items (Base64 `data` or stdio-only `file_path`) and returns a
presigned GET `url` and an `object_key` per item, in request order.

- **Items fail independently** and the call still succeeds: **always check
  `failed` and each `items[].error`**; re-upload only `retryable=true` items and
  fix the input of the rest.
- **Only an over-size request fails the whole call.** The total decoded size is
  checked before anything uploads against `MEDIA_UPLOAD_BATCH_MAX_BYTES`
  (default 500 MiB): split into smaller calls. Per-item size limits (video
  200 MiB) fail just that item.
- **`mime_type`** is required for `data` items and inferred from the extension
  for `file_path` items; if inference fails that item errors, so set it for
  unusual extensions.
- **`expires_in_seconds`:** use a sufficiently long TTL (e.g. 3600) when a provider
  fetches asynchronously and a default-TTL URL can expire first. It applies to
  every item in the call.
- **Keep each returned `object_key`** for `media_presign` reuse without
  re-uploading. It is not a provider asset ID.

### `media_presign`

Mints fresh URLs for 1-100 `object_keys` without re-uploading. Read-only,
foreground on stdio only. HTTP does not expose this URL-renewal tool. Each
key fails on its own, so check `failed` and per-key `code`:

| `code` | Meaning and fix |
|---|---|
| `INVALID_KEY` | Malformed key; use it exactly as `media_upload` returned it |
| `NOT_OWNED` | Not uploaded by this caller; re-upload |
| `INTERNAL` | Unexpected server error; retry |
| provider code | S3 rejected it (object missing, credentials); see `error`, `request_id` |

### Presign-reuse pattern

Presigned URLs expire (default 30 minutes; `S3_PRESIGN_TTL_SECONDS`). When the same references (character sheets, a music
bed) feed many shots, **upload once, then presign per shot**:

1. Upload all references in one `media_upload` call, check `failed`, and store
   each `object_key` in the project's reference registry.
2. Right before each submission, `media_presign` the keys that shot needs, check
   per-key `code`, and submit immediately while the URLs are valid.

## Managed Files

Managed reference files use `ark_file_upload`, `ark_file_get`,
`ark_file_list`, and `ark_file_delete` with the ModelArk API key. Default
`purpose="agent"` uses provider-managed storage without bucket setup. Retrieve
the accepted file ID until active with a `download_url`, then pass that URL
to generation. The client-side `seed-mcp-upload` streams local files directly
to ModelArk; HTTP MCP accepts HTTPS source URLs, not local paths or Base64.
Reads do not renew the documented 24-hour/100-download URL limit. No upload
enrollment, TOS signer, IRSA, application file database or cleanup worker remains.
Never automatically retry an uncertain upload/delete; keep file/request IDs.

On HTTP, all four Files tools require the user's own `X-ModelArk-Api-Key`
and optional `X-MCP-Client-Secret`; neither is persisted by the MCP server.
The client secret separates admission, not file ownership. No TOS bucket or
operator upload enrollment is needed. Check tools/list before use: source
support and local smoke results do not establish public cloud availability.

Use `seed-mcp-upload --file /absolute/reference.mp4 --api-key-env
BYTEPLUS_MODELARK_API_KEY --confirm-upload` only after exact-file consent.
Get/list/delete can affect files authorized by a shared provider key.
Deletion requires explicit `confirm=true`; wait for dependent generation first.
The helper emits the ID, not signed URLs, and reads no .env/client config.
Local uploads are capped at 512,000,000 bytes. Retention defaults to seven
days; `expire_at` can select 1-30 days. Provider-managed storage is documented
as 20 GB per account. Never call these URLs permanent assets.

## Native Seedance assets

Existing authorized `asset://<id>` references are passed to Seedance without
downloading or resolving them. Use them in `images`, `videos` or `audios`,
and refer to inputs by position in the prompt. Both transports require only
the normal ModelArk key for generation.

Asset creation, verification, status checks and administration happen outside
this server. A dry run does not prove an asset is active or authorized. Other
products do not support native asset references, and an ordinary object-storage
upload does not create a provider asset.
