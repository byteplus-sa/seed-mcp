# Managed Reference Files

Use ModelArk's Files API without creating or authorizing a storage bucket.
The four tools are `ark_file_upload`, `ark_file_get`, `ark_file_list`, and
`ark_file_delete`. They use the ModelArk API key, on both HTTP and stdio.
TOS signing, temporary-upload enrollment, IRSA, and the TOS storage backend
have been removed. Independent local S3 storage and artifacts remain optional.

## Basic Setup

- **Hosted HTTP:** configure your own `X-ModelArk-Api-Key` for all four Files tools.
  `X-MCP-Client-Secret` is optional; [manual setup](setup/install.md#optional-client-secret)
  separates client admission, not file access.
- **Local stdio:** configure `BYTEPLUS_MODELARK_API_KEY`.
- **Client-side uploader:** supply the ModelArk key through the named environment
  variable. It talks directly to ModelArk, not MCP, and needs no client secret.

The server does not persist these credentials or fall back to operator keys.
No TOS bucket, storage AK/SK or upload enrollment is needed. Confirm the
connected deployment exposes all four tools; source support is not deployment
evidence. Access remains subject to your key's ModelArk permissions.

Seed Audio generation still uses a separate Seed Speech key. A Files upload
does not grant generation entitlement or authorize a voice.

## Upload A Local File

A remote MCP server cannot read paths on your computer. Install this package
in the file-capable client's execution environment, then run:

```bash
seed-mcp-upload --file /absolute/reference.mp4 \
  --api-key-env BYTEPLUS_MODELARK_API_KEY --confirm-upload
```

The helper reads only that environment variable, not `.env`, client config,
provider profiles, or server settings. Confirm the exact selected file and
destination before transfer. It streams at most **512,000,000 bytes** directly
to the fixed official ModelArk origin with TLS verification, no redirects,
no inherited HTTP proxy settings, no automatic retry, and no local output file.
The output is metadata containing `id`; signed URLs and keys are not printed.
Only regular files are accepted; the final path must not be a symlink.
Platforms without no-follow/nonblocking file-open support fail closed.
Changes detected during transfer produce an uncertain failure, not an automatic
second upload. There is no checksum-based provider deduplication.

This is a client utility, not a second MCP server. Clients without local
filesystem/command access must use an already hosted HTTPS source or arrange
an explicitly authorized uploader.

On stdio, the MCP upload tool also accepts an absolute path on the server host:

```json
{"input":{"file_path":"/absolute/reference.mp4","purpose":"agent"}}
```

## Upload From A URL

On either transport, call `ark_file_upload`:

```json
{"input":{"url":"https://example.com/reference.png","purpose":"agent"}}
```

Provide exactly one of `url` or `file_path`. HTTP rejects local paths and Base64;
its 2 MiB default request-body cap is unchanged. Only public HTTPS source URLs
are accepted. The provider fetches the URL; this server neither proxies those
bytes nor proves the provider's redirect handling. There is no `tos`, bucket,
prefix, storage credential, arbitrary API origin, or `idempotency_key` input.

The default purpose is **`agent`**, which provides a download URL through file
retrieval/listing. `user_data` is available for understanding workflows, but
does not promise a downloadable generation reference. Upload can return without
`download_url` even when the file is already active.

## Retrieve And Use

Keep the returned ID and call `ark_file_get`:

```json
{"input":{"file_id":"file-EXAMPLE"}}
```

Wait while `status="processing"`; a few seconds between reads is reasonable.
Use the reference only when `status="active"` and `download_url` is present.
Do not upload again to poll, or infer readiness from upload acceptance alone.
If status is failed, inspect the sanitized processing error.

Pass the **complete `download_url`**, including its signature query, into:

| Tool | Reference input |
| --- | --- |
| `seedance_create_task` | `images`, `videos`, or `audios` |
| `seedream_generate_image` | `images: [{"kind":"url","url":"..."}]` |
| `seed_audio_generate` | `image_reference` or `audio_references` with `kind="url"` |

The generation tools do not resolve `file_id`. File size acceptance is not
model acceptance: each model's media formats, dimensions, durations, counts,
rights and consent requirements still apply. TTS 3 synthesis uses text/SSML
and an authorized voice ID; it has no direct reference-file input. Voice
registration remains a separate provider workflow, not part of this server.

## List And Delete

`ark_file_list` returns one page, defaulting to purpose `agent`, newest first,
20 files. `limit` accepts 1-100; `purpose=null` omits the purpose filter.

```json
{"input":{"purpose":"agent","limit":20,"order":"desc"}}
```

When `has_more=true`, pass the returned `last_id` as `after`. No automatic
pagination, local ownership filter, file download or URL renewal occurs.

`ark_file_delete` requires explicit boolean confirmation:

```json
{"input":{"file_id":"file-EXAMPLE","confirm":true}}
```

Deletion is permanent. Wait until all generation tasks using the reference
finish. Provider authorization determines access: clients sharing a key share
whatever file access the provider permits, regardless of client secret.

## Limits And Recovery

ModelArk documents **512 MB per file** and **20 GB free managed storage per
account**. Storage defaults to seven days; optional `expire_at` is a UTC Unix
timestamp 1-30 days from now. ModelArk owns expiry; this server has no cleanup
job, file database, replay store or retention guarantee beyond the provider
contract.

Download URLs have a separate documented **24-hour validity and 100-download
limit**. Metadata reads return the same saved link and do not refresh either
limit. File retention is not URL validity. Keep signed URLs out of logs and
public documents. A URL is a bearer capability, not a private key-authenticated
download endpoint.

All four operations are single-attempt direct calls with bounded admission
and response metadata (2 MiB maximum). Upload/delete failures after dispatch
may be uncertain. Retain accepted file/request IDs and reconcile; do not
automatically resubmit. The client uploader has a 600-second cooperative bound.
HTTP retains accepted IDs only in the live invocation for deadline diagnostics.

## Evidence

The 2026-11-28 live smoke on `fa8cf76` passed stdio upload, local HTTP BYOK
URL import, and client-helper upload, with byte-identical downloads and verified
deletion. No deployment or generation calls were made. A post-deployment smoke
is still required; see [the evidence record](hosted-deployment-status.md#managed-files-source-validation).

On 2026-11-28, approved synthetic tests successfully used Files
`purpose=agent` download URLs with Seedream 5.5, regular Seedance 2.5
(image/video/audio together), and Seed Audio 1.0 (image and audio separately).
This establishes those tested combinations, not every account, format or
model. A later image-guided Seed Audio review rerun returned provider HTTP 500;
no automatic retry was made. TTS was checked against its contract, not synthesized.

Sources, accessed 2026-11-28:
[upload](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/upload-files-api),
[retrieve](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/search-files-api),
[list](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/list-files-api),
[delete](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/delete-files-api).
