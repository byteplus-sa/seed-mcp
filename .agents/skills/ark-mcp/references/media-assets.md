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
or use optional temporary preparation below.

| Tool | Mode | Needs |
|---|---|---|
| `media_upload` | direct | object storage (TOS or S3) |
| `media_presign` | direct | object storage |

Use a 660-second client timeout for the default 600-second cooperative tool
deadline. SDK threads drain before admission slots or clients are released,
so cancellation cleanup can exceed that deadline. Never blindly retry an
uncertain upload. See [local-output.md](local-output.md).

## Object storage (`media_upload`, `media_presign`)

Needed whenever a tool takes media as a URL only (Seedance video/audio
references). TOS or S3 makes no difference
to tool behaviour.

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
| provider code | TOS/S3 rejected it (object missing, credentials); see `error`, `request_id` |

### Presign-reuse pattern

Presigned URLs expire (default 30 minutes; `TOS_PRESIGN_TTL_SECONDS` /
`S3_PRESIGN_TTL_SECONDS`). When the same references (character sheets, a music
bed) feed many shots, **upload once, then presign per shot**:

1. Upload all references in one `media_upload` call, check `failed`, and store
   each `object_key` in the project's reference registry.
2. Right before each submission, `media_presign` the keys that shot needs, check
   per-key `code`, and submit immediately while the URLs are valid.

## Temporary HTTP References

`media_prepare_upload` is HTTP-only, disabled by default, and shared across
image/audio/video references. Check tools/list; anonymous discovery is not
upload entitlement. An operator-enrolled client secret authorizes signing
without a generation-provider key. Preparation takes metadata only and does
not receive bytes, access the client's files, inspect media or verify existence.

1. Send `{"input":{"media_type":"image","mime_type":"image/png","size_bytes":1234}}`,
   using the actual binary byte size and exact allowed MIME. Caps: 10 MiB
   image/audio, 200 MiB video.
2. An upload-capable client sends multipart POST to `upload_url`, every
   `form_fields` value unchanged, then binary `file` LAST. Wait for success.
3. Use the complete `reference_url` in existing generation inputs with normal
   provider BYOK headers, promptly enough for queued provider fetches.

The server selects a unique exact key; private ACL, STANDARD storage, exact
declared MIME/byte size, forbid-overwrite and one-day object expiry are signed.
POST expires in 15 minutes; GET in 24 hours from preparation. STS expiry can
shorten both. Signed fields/URLs are sensitive bearer permissions, not
guaranteed one-use tokens. Never log or publish them.
URL expiry does not delete data; one-day object expiry is scheduled from
Last-Modified/following midnight, not exact 24-hour deletion.
There is no HTTP renewal/finalization tool, upload record or global storage/
egress budget. Client attachment alone does not perform this upload.

Operator signing can use static AK/SK or explicit VKE IRSA with lazily refreshed
temporary credentials. IRSA changes no client inputs or generation BYOK headers.
Its default one-hour STS session can shorten nominal GET validity to an hour
or less; refresh never extends issued URLs. Use an independently managed
reference source when longer validity is required. Credential-unavailable
errors require operator STS/trust/token diagnosis, not submitting generation
keys to the server or enabling IAM automatically.

Operators enable `MCP_TEMPORARY_UPLOAD_ENABLED` with TOS and
`MCP_UPLOAD_CLIENT_SECRET_SHA256`: 1-1000 unique lowercase digests of exact ASCII
client-secret values (not decoded bytes), comma-separated without spaces.
Require private dedicated bucket, versioning disabled, restricted prefix IAM,
browser POST CORS as needed, lifecycle backstop and abuse/spend controls.
These are separate approved operator actions. Read `docs/temporary-uploads.md`
in the selected checkout for configuration and client-side multipart code.

## Native Seedance assets

Existing authorized `asset://<id>` references are passed to Seedance without
downloading or resolving them. Use them in `images`, `videos` or `audios`,
and refer to inputs by position in the prompt. Both transports require only
the normal ModelArk key for generation.

Asset creation, verification, status checks and administration happen outside
this server. A dry run does not prove an asset is active or authorized. Other
products do not support native asset references, and an ordinary object-storage
upload does not create a provider asset.
