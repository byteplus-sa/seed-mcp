# API Keys Guide

HTTP BYOK uses your provider key in the selected `X-ModelArk-Api-Key`,
`X-Seed-Speech-Api-Key` or `X-OmniHuman-Api-Key` header, plus
`X-MCP-Client-Secret` (client-generated 32 random bytes as 64 lowercase hex).
Only the selected key is needed. Discovery is anonymous/static and never
validates your provider entitlement. See [private HTTP setup](setup/shared-server.md).
There is no OAuth, signup or server-issued key; `Authorization` is rejected.

The table below describes **local stdio startup settings and upstream auth**,
not HTTP client header names. Hosted provider-secret sync is
[superseded](secret-manager.md). The operator's `MCP_IDENTITY_HMAC_KEY` is
identity configuration, not a customer credential.

This server calls several BytePlus services. Each uses a distinct credential
and auth scheme — they are **not interchangeable**. You only need the keys for
the products you want to use. On stdio, absent credentials omit that tool set;
HTTP registration is credential-independent (OmniHuman still needs its flag).

| Service | Env var | Auth header | Tools it enables |
|---|---|---|---|
| ModelArk | `BYTEPLUS_MODELARK_API_KEY` | `Authorization: Bearer <key>` | Seedream and Seedance |
| Seed Speech | `BYTEPLUS_SEED_SPEECH_API_KEY` | `X-Api-Key: <key>` | Seed Audio generation |
| Vision AI (OmniHuman) | `BYTEPLUS_CV_API_KEY` | `Authorization: Bearer <key>` | `omnihuman_*` tools (also needs `BYTEPLUS_OMNIHUMAN_ENABLED=true`) |
| TOS | `TOS_ACCESS_KEY` + `TOS_SECRET_KEY` + `TOS_BUCKET` | AK/SK signing | `media_upload`, `media_presign` |
| S3 | `S3_ACCESS_KEY` + `S3_SECRET_KEY` + `S3_BUCKET` | AK/SK signing | `media_upload`, `media_presign` |

With [guided setup](setup/install.md), your agent prepares a private blank
credential file and opens it for you. **Enter keys there, not in chat or MCP
client JSON.** You do not need to copy the full example configuration or
configure services you do not use. HTTP clients supply their own provider
headers privately; the operator must be trusted with those live requests.

All env keys below are **local startup configuration**, never tool arguments. The
examples are field-name references for that private file, not shell commands.
Preserve existing files and keep credentials outside repositories and shared
folders. See [manual credential setup](setup/manual-install.md#prepare-private-credentials)
only when preparing the file yourself.

## ModelArk

ModelArk provides **Seedream** and **Seedance**. The key is sent as a Bearer token.

**Env vars:**

| Variable | Default | Purpose |
|---|---|---|
| `BYTEPLUS_MODELARK_API_KEY` | empty | ModelArk API key |
| `BYTEPLUS_MODELARK_BASE_URL` | `https://ark.ap-southeast.bytepluses.com/api/v3` | Region-scoped data-plane host |

**How to get the key:**

1. Sign in to the BytePlus console at **<https://console.byteplus.com>**.
2. Open **ModelArk** (Ark) and navigate to **API Key** management.
3. Create a new API key. Copy it immediately — it is shown once.
4. (Optional) Create an **inference endpoint** for the Seedream or Seedance
   model you want to use, then set its ID as `SEEDREAM_DEFAULT_MODEL` or
   `SEEDANCE_DEFAULT_MODEL`. The built-in defaults already have known families;
   a custom endpoint ID must be bound via `SEEDREAM_MODEL_BINDINGS` /
   `SEEDANCE_MODEL_BINDINGS`.

```dotenv
BYTEPLUS_MODELARK_API_KEY=your-modelark-key-here
```

The base URL is region-scoped. Local stdio can configure another HTTPS provider
base; HTTP fixes official origins and never accepts arbitrary endpoint hosts.

## Seed Speech

Seed Speech provides **Seed Audio** (full-scene audio generation / TTS).
It is separate from ModelArk and uses `X-Api-Key`, not Bearer.

**Env vars:**

| Variable | Default | Purpose |
|---|---|---|
| `BYTEPLUS_SEED_SPEECH_API_KEY` | empty | Seed Audio generation key |
| `BYTEPLUS_SEED_AUDIO_BASE_URL` | `https://voice.ap-southeast-1.bytepluses.com` | Seed Speech host |

**How to get the key:**

1. Sign in to **<https://console.byteplus.com>**.
2. Open **BytePlus Voice** (or Seed Speech / Speech Studio).
3. Navigate to API key or application management and create a key.
4. Copy the key. It is distinct from your ModelArk key.

The key must belong to an application with Seed Audio access. Without that
entitlement, provider calls are rejected with an auth/resource error even
when the key itself is valid.

```dotenv
BYTEPLUS_SEED_SPEECH_API_KEY=your-seed-speech-key-here
```

## BytePlus Vision AI (OmniHuman)

**Env vars:**

| Variable | Default | Purpose |
|---|---|---|
| `BYTEPLUS_CV_API_KEY` | empty | Vision AI Bearer key |
| `BYTEPLUS_OMNIHUMAN_ENABLED` | `false` | Registers the `omnihuman_*` tools |
| `BYTEPLUS_CV_BASE_URL` | `https://openapi.cv.bytepluses.com` | Vision AI base URL |

Create the key under Access Key Management in the BytePlus console and make
sure the account has OmniHuman 2.0 enabled. The same service also accepts
AK/SK-signed requests on `cv.byteplusapi.com`; this server uses the API-key
path only.

## Object storage (TOS or S3)

Local upload/presign and artifacts are stdio-only. Opt-in HTTP
[temporary preparation](temporary-uploads.md) uses separate restricted operator
TOS credentials and enrolled client-secret digests, not customer AK/SK.

Object storage is **optional** but enables several workflows: the `media_upload` and
`media_presign` tools and Seedance video references
(URL-only). It uses Access Key / Secret Key (AK/SK) signing, not a bearer
token. Select the backend with `OBJECT_STORAGE_BACKEND` (`tos` default, or
`s3`).

### TOS backend

**Env vars:**

| Variable | Default | Purpose |
|---|---|---|
| `TOS_ACCESS_KEY` | empty | Access Key (AK) |
| `TOS_SECRET_KEY` | empty | Secret Key (SK) |
| `TOS_SECURITY_TOKEN` | empty | Optional temporary token (STS only) |
| `TOS_BUCKET` | empty | Target bucket name |
| `TOS_REGION` | `ap-southeast-1` | Bucket region |
| `TOS_ENDPOINT` | `tos-ap-southeast-1.bytepluses.com` | TOS API endpoint |
| `TOS_PRESIGN_TTL_SECONDS` | `1800` | Presigned URL validity in seconds (60–604800) |

`TOS_ACCESS_KEY` and `TOS_SECRET_KEY` must **both** be set or **both** be
empty. All three of AK, SK, and bucket must be set to register the
`media_upload` and `media_presign` tools.

**How to get the keys:**

1. Sign in to **<https://console.byteplus.com>**.
2. Open **TOS** (Object Storage).
3. Create a **bucket** (keep it **private**) in your target region. Note the
   bucket name and region — set them as `TOS_BUCKET` and `TOS_REGION`.
4. For the access keys: open **IAM** (Identity and Access Management) and
   create an access key pair (AK + SK) for a user or service account that has
   read/write permission on that bucket. Copy both immediately — the SK is
   shown once.

```dotenv
TOS_ACCESS_KEY=your-access-key
TOS_SECRET_KEY=your-secret-key
TOS_BUCKET=your-private-bucket
TOS_REGION=ap-southeast-1
TOS_ENDPOINT=tos-ap-southeast-1.bytepluses.com
```

**Security notes:**

- Keep the bucket **private**. The server never makes objects public; it
  generates short-lived presigned GET URLs (default 30 minutes, configurable via
  `TOS_PRESIGN_TTL_SECONDS`) for individual objects.
- Uploaded objects are **not auto-deleted** by this server. Configure a TOS
  bucket lifecycle rule to expire objects under the upload prefixes
  (for example, `references/`) to control storage cost over time.
- For temporary credentials (STS), also set `TOS_SECURITY_TOKEN`.

### S3 backend

| Variable | Default | Purpose |
|---|---|---|
| `S3_ACCESS_KEY` | empty | S3 access key ID |
| `S3_SECRET_KEY` | empty | S3 secret access key |
| `S3_BUCKET` | empty | Target bucket name |
| `S3_REGION` | `us-east-1` | AWS region |
| `S3_ENDPOINT` | empty | Custom endpoint for S3-compatible storage |
| `S3_PRESIGN_TTL_SECONDS` | `1800` | Presigned URL validity in seconds (60–604800) |
| `OBJECT_STORAGE_BACKEND` | `tos` | Select active backend: `tos` or `s3` |

`S3_ACCESS_KEY` and `S3_SECRET_KEY` must **both** be set or **both** be
empty. All three of AK, SK, and bucket must be set to register the
`media_upload` and `media_presign` tools with the S3
backend.

When `S3_ENDPOINT` is set, path-style addressing is used automatically for
S3-compatible storage (MinIO, R2, TOS-via-boto3).

## Verifying your setup

After saving the private file, reconnect Ark through your client's MCP
settings, taking care to finish active calls first. The client starts the
server automatically. Use the [discovery-only connection check](integrations/index.md#verify-without-paid-calls);
do not start development mode just to test keys.

The stdio-only `seed-health://status` MCP resource reports configured services and storage
without exposing keys. The separate `/health` HTTP route is a liveness probe that returns
only `{"status": "healthy"}`. A disabled service may have a missing key or
feature flag. Ask your setup agent to check names and the configured
`ARK_MCP_ENV_FILE` path without reading or printing key values.

On stdio, a missing provider key omits its tools. HTTP always exposes the
7 supported provider/discovery tools, or 10 with OmniHuman enabled.
Discovery confirms configuration, not provider-key validity or account access.

## Quick reference

```dotenv
# ModelArk — image + video
BYTEPLUS_MODELARK_API_KEY=
BYTEPLUS_MODELARK_BASE_URL=https://ark.ap-southeast.bytepluses.com/api/v3

# Seed Speech — Seed Audio generation
BYTEPLUS_SEED_SPEECH_API_KEY=
BYTEPLUS_SEED_AUDIO_BASE_URL=https://voice.ap-southeast-1.bytepluses.com

# Vision AI — OmniHuman (optional)
BYTEPLUS_CV_API_KEY=
BYTEPLUS_OMNIHUMAN_ENABLED=false
BYTEPLUS_CV_BASE_URL=https://openapi.cv.bytepluses.com

# Object storage — TOS (optional, default backend)
TOS_ACCESS_KEY=
TOS_SECRET_KEY=
TOS_BUCKET=
TOS_REGION=ap-southeast-1
TOS_ENDPOINT=tos-ap-southeast-1.bytepluses.com
TOS_PRESIGN_TTL_SECONDS=1800

# Object storage — S3 (optional alternative backend)
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET=
S3_REGION=us-east-1
S3_ENDPOINT=
S3_PRESIGN_TTL_SECONDS=1800
OBJECT_STORAGE_BACKEND=tos
```

Console: **<https://console.byteplus.com>**
Docs: **<https://docs.byteplus.com>**
