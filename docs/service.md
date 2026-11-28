---
title: Service Limits and Privacy
description: What the hosted service provides, how it handles requests, and what to keep.
---

## Availability

The hosted service exposes eight baseline tools for discovery, Seedream images,
Seedance video, Seed Audio and Seed TTS. Your provider account must authorize the model
you choose. Discovery lists configuration, not entitlement.

Local file uploads, artifact resources, ASR, 3D and provider asset
administration are not hosted features. Temporary uploads are disabled.
Use provider-accessible HTTPS URLs for references; attaching a file in chat
does not upload it automatically. Small inline inputs remain subject to the
request limit.

Seed TTS 3 returns complete native audio directly, up to 30 MiB decoded audio.
Save the returned audio block using your client; playback and saving UI vary.
No TOS, download URL or later recovery is provided. Check discovery for the
connected deployment's current tools.

## Outputs and Limits

| Item | What to expect |
| --- | --- |
| Image and video links | Expire after about 24 hours |
| Audio links | Expire after about two hours |
| Client tool timeout | Use 660 seconds |
| Request body | Maximum 2 MiB |
| Rate and concurrency | Limited per server replica; reduce parallel calls when busy |

Download provider URLs or save inline TTS audio you want to keep. Hosted TTS
is not stored by the server; it cannot be recovered after a lost response.

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

Your provider key controls access to provider tasks. Clients sharing a key
share whatever access that provider permits. The independent client secret
separates admission limits; it is not a separate task-ownership boundary.

For local installations or operations, use the
[repository handbook](https://github.com/byteplus-sa/seed-mcp/tree/main/docs).
This site documents its build revision, not a service availability SLA.
