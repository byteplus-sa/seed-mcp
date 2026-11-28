---
title: Service Limits and Privacy
description: What the hosted service provides, how it handles requests, and what to keep.
---

## Availability

This source revision exposes twelve hosted tools for discovery, managed Files,
Seedream images, Seedance video, Seed Audio and Seed TTS. Check the connected
deployment's tools/list; source changes are not deployment evidence.
Discovery lists configuration, not provider entitlement.

Local file uploads, artifact resources, ASR, 3D and provider asset
administration are not hosted features. Managed Files import HTTPS URLs;
the [client-side helper](files.md) streams local files to ModelArk without a bucket.
Chat attachments do not upload automatically.

All four Files operations use your own ModelArk API key with an optional independent
client secret. No storage credentials or upload enrollment are needed.

Seed TTS 3 returns complete native audio directly, up to 30 MiB decoded audio.
Save the audio using your client; playback support varies.
No TOS, download URL or later recovery is provided.

## Outputs and Limits

| Item | What to expect |
| --- | --- |
| Image and video links | Expire after about 24 hours |
| Audio links | Expire after about two hours |
| Files reference links | Documented 24 hours / 100 downloads; metadata reads do not renew them |
| Client tool timeout | Use 660 seconds |
| Request body | Maximum 2 MiB |
| Rate and concurrency | Limited per server replica; reduce parallel calls when busy |

Download generated media you want to keep. Hosted TTS is not stored or recoverable.

## Costs

Generation is billed to your provider account. Discovery is free.
Seedream and Seedance support non-billable `dry_run` previews, but still require
private headers. Preview estimates are built-in estimates, not account quotes.
Use provider-side spend controls; the hosted service has no shared budget ledger.

## Privacy

The service receives your prompts, media references and live provider keys.
Provider keys are not persisted by the MCP server. It forwards work to the
selected BytePlus provider; this is not a promise about provider retention.
Only connect if you trust the operator.

Public HTTPS certificate verification remains enabled. For this deployment,
the operator accepted an exception on the private gateway-to-server hop:
HTTPS encrypts it, but the gateway does not establish the backend certificate's
identity. This carries a private-hop impersonation and credential-exposure risk.
See the [documented exception](../specs/SPEC_VKE_DEPLOYMENT.md#accepted-backend-verification-exception)
and [dated deployment evidence](hosted-deployment-status.md#connect).

Your provider key controls access to provider tasks and files. Clients sharing a key
share whatever access that provider permits. The independent client secret
separates admission limits; it is not a separate task or file ownership boundary.

Local setup and operations: [repository handbook](https://github.com/byteplus-sa/seed-mcp/tree/main/docs).
