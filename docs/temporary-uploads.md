# Temporary Reference Uploads

Hosted HTTP can optionally expose `media_prepare_upload` for operator-funded
temporary TOS storage. It is disabled by default and requires operator enrollment.
No application database, upload proxy, finalization endpoint or cleanup worker
is added. `media_upload` and `media_presign` remain stdio-only.

## Client Workflow

1. Call `media_prepare_upload` with metadata and an enrolled
   `X-MCP-Client-Secret` in private headers. No generation-provider key is needed
   for this preparation call.
2. Upload the binary directly to `upload_url` using multipart POST. Include
   every `form_fields` entry unchanged and append `file` **last**. Let the HTTP
   library choose the multipart boundary.
3. Wait for a successful TOS upload. The preparation result is not an upload
   receipt and does not prove that the file exists.
4. Pass `reference_url` into an existing generation tool with its usual BYOK
   headers. Submit promptly so queued provider workers can fetch before expiry.

```json
{
  "name": "media_prepare_upload",
  "arguments": {
    "input": {
      "media_type": "video",
      "mime_type": "video/mp4",
      "size_bytes": 1048576
    }
  }
}
```

`size_bytes` must be the exact binary file size, not the multipart request size.
Images and audio are capped at 10 MiB; video at 200 MiB. MIME types must exactly
match the category's allowlist in the tool schema/runtime. MIME is declared
metadata, not inspection of the bytes or proof of valid media.

An upload-capable integration can consume the structured result as follows.
This example is client-side code, not a new MCP endpoint or an automatic upload
performed by the server:

```python
from pathlib import Path

import httpx


def upload_reference(prepared: dict, path: Path, mime_type: str) -> str:
    if path.stat().st_size != prepared["size_bytes"]:
        raise ValueError("File size changed; prepare again with the exact size.")
    with path.open("rb") as file:
        # httpx encodes data fields before the final binary file part.
        response = httpx.post(
            prepared["upload_url"],
            data=prepared["form_fields"],
            files={prepared["file_field"]: (path.name, file, mime_type)},
            timeout=300,
            follow_redirects=False,
        )
    response.raise_for_status()
    return prepared["reference_url"]
```

After upload success, a Seedance call can use:

```json
{
  "name": "seedance_create_task",
  "arguments": {
    "input": {
      "prompt": "Use Video 1 as the movement reference.",
      "videos": ["https://your-bucket.tos-ap-southeast-1.bytepluses.com/temporary-references/replace-with-returned-signed-url"]
    }
  }
}
```

Use the complete returned URL, including its signature query, not the illustrative
URL above. Seedream uses `images`; audio references use the selected tool's audio
fields. Generation schemas and model limits remain unchanged. An AI-client
attachment alone does not upload to TOS; the client needs filesystem access and
an HTTP multipart uploader or a separately approved helper.

## Fixed Permissions

| Permission | Duration or restriction |
| --- | --- |
| POST authorization | 15 minutes (900 seconds) |
| GET reference URL | 24 hours (86400 seconds), minted before upload |
| Object expiry | `x-tos-object-expires=1`, one whole day |
| Object key | Server-selected `temporary-references/{HMAC principal}/{media_type}/{uuid4}` |
| POST policy | Exact key, exact declared MIME and byte count, private ACL, STANDARD storage, forbid overwrite |

No caller-selected bucket, prefix, endpoint, ACL or lifetime is accepted.
Signed fields and URLs are sensitive bearer capabilities. Never publish them
or log the structured result; the fields can include an STS token. They are not
guaranteed one-use tokens. Effective permission lifetime may end earlier when
the signing STS credentials expire.

URL expiration is not object deletion. TOS expiry is day-based from
Last-Modified, with deletion starting at the following midnight and scheduled
asynchronously, not precisely 24 hours after upload. One-hour object deletion
is not offered by this implementation. Object expiry takes priority over
lifecycle deletion rules. Versioning can retain historic data and defeat
forbid-overwrite, so use a dedicated bucket with versioning **disabled**, not
enabled or suspended.

## Operator Setup

Configure these securely outside Git:

| Setting | Value |
| --- | --- |
| `MCP_TEMPORARY_UPLOAD_ENABLED` | `true` on HTTP only; default `false` |
| `MCP_UPLOAD_CLIENT_SECRET_SHA256` | 1-1000 unique lowercase SHA-256 digests, comma-separated without spaces |
| `OBJECT_STORAGE_BACKEND` | `tos`; S3 upload preparation is not supported |
| `TOS_ACCESS_KEY`, `TOS_SECRET_KEY`, `TOS_BUCKET` | Dedicated restricted signing credentials and private bucket |
| `TOS_SECURITY_TOKEN` | Optional STS token; operator owns rotation |
| `TOS_REGION` | Regional identifier, e.g. `ap-southeast-1` |
| `TOS_ENDPOINT` | Exact `tos-{TOS_REGION}.bytepluses.com`, optionally prefixed with `https://`; no port/path |

The allowlist digest is SHA-256 of the **exact 64-character ASCII header value**,
not of its hex-decoded bytes. Client secrets are generated from 32 random bytes.
Enroll only approved clients; a self-selected well-formed secret and a provider
key do not establish upload entitlement. Do not collect raw client secrets in
chat. Removing enrollment blocks future preparation after every pod reloads
configuration, but does not revoke already issued signed permissions.

Before enabling:

- Verify a dedicated private bucket with versioning disabled and public access
  denied. Restrict signing IAM to PutObject/GetObject under `temporary-references/`.
- Add browser POST CORS for approved client origins if browser uploads are
  needed; configure CORS independently of MCP ingress.
- Configure a prefix-scoped lifecycle deletion backstop and verify native
  object-expiry behavior with the selected bucket.
- Set operator storage/egress alerts and abuse controls. Per-pod preparation
  rates and concurrency do not impose global byte, object or spend quotas.
- Check signer credential lifetime, rotation and provider queue/fetch timing.
  Readiness is lifespan-only and does not probe TOS.

Helm accepts `temporaryUpload.enabled: true` and
`temporaryUpload.existingSecret: <existing-name>`. The Secret must differ from
identity and TLS Secrets. Required fixed keys are `TOS_ACCESS_KEY`,
`TOS_SECRET_KEY`, `TOS_BUCKET`, `TOS_REGION`, `TOS_ENDPOINT`, and
`MCP_UPLOAD_CLIENT_SECRET_SHA256`; `TOS_SECURITY_TOKEN` is optional. Do not put
values in Helm values or Terraform state. Roll pods after Secret changes;
the chart checksum cannot observe external Secret content.

The server does not configure IAM, bucket privacy, versioning, CORS or lifecycle,
inspect uploaded bytes, verify upload completion, renew these references, or
retain upload records. Live bucket/client/provider acceptance remains an
operator gate separate from offline signing tests.

## Sources

Official documentation, accessed 2026-11-18:

- [TOS POST form presigning](https://docs.byteplus.com/en/docs/tos/Post-form-pre-signature-python-sdk)
- [TOS PostObject](https://docs.byteplus.com/docs/tos/reference-postobject)
- [TOS object expiration](https://docs.byteplus.com/docs/tos/Set-expiration-times)
- [TOS lifecycle rules](https://docs.byteplus.com/en/docs/tos/docs-setting-lifecycle-rules)

Durable contract: [Hosted BYOK](../specs/SPEC_HOSTED_BYOK.md#temporary-upload-preparation).
