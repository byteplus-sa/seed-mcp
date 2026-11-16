---
title: Provider Secret Manager Sync Contract
type: spec
status: deprecated
horizon: current
created: 2026-11-13
updated: 2026-11-16
tags: [deployment, secrets, kms, security]
source:
  - https://docs.byteplus.com/en/docs/kms/Request_structure
  - https://docs.byteplus.com/en/docs/kms/DescribeSecret
  - https://docs.byteplus.com/en/docs/kms/GetSecretValue
related:
  - specs/SPEC_HOSTED_BYOK.md
  - docs/secret-manager.md
---

# Provider Secret Manager Sync Contract

Superseded by [SPEC_HOSTED_BYOK.md](SPEC_HOSTED_BYOK.md) on 2026-11-16.
Hosted HTTP has no operator provider-key bundle to synchronize: credentials
arrive only on each customer's live request and are never persisted.

Do not use the former hosted provider-secret deployment or `config` sync
workflow for this foundation. No compatibility migration or adoption of old
hosted state is provided. Retain older deployment history separately; do not
reapply it to provision keys or jobs for BYOK.

The operator's `MCP_IDENTITY_HMAC_KEY` is separate identity configuration,
not a customer credential or a provider-key replacement. Keep it stable and
private; changing it changes derived ownership. Local stdio may still load
provider keys from a private env file through `ARK_MCP_ENV_FILE`.

This deprecated specification is retained as a pointer, not current setup
instructions. It does not authorize Secret Manager reads, writes or live sync.
