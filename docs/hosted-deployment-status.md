---
title: Hosted Deployment Status
---

# Hosted Deployment Status

**Verified public on November 28, 2026, at 08:19 UTC.** This is a point-in-time
record for the operator's existing Seed MCP deployment, not a general
availability SLA or a default target for other installations.

## Connect

Streamable HTTP MCP endpoint:

```text
https://st63a28rvt0o3d9htd28d.apigateway-ap-southeast-1.apigw-byteplus.com/mcp
```

The same origin's `/health` returns `{"status":"healthy"}`. MCP discovery is
anonymous. Generation requires the selected `X-ModelArk-Api-Key` or
`X-Seed-Speech-Api-Key`, plus an independent `X-MCP-Client-Secret` containing
32 random bytes encoded as 64 lowercase hexadecimal characters. Configure
credentials privately in the client; do not use `Authorization` or tool
arguments for keys. Use a 660-second client timeout.

This deployment retains the operator's
[scoped backend-verification exception](../specs/SPEC_VKE_DEPLOYMENT.md#accepted-backend-verification-exception):
public HTTPS is verified, and the private APIG-to-Caddy hop is encrypted, but
APIG backend certificate identity verification is not established. Direct
certificate checks do not change that accepted impersonation/credential-exposure
risk. Do not generalize the exception to another deployment.

## Deployed Instance

| Item | Verified value |
| --- | --- |
| Account / region | `3000006864` / `ap-southeast-1` |
| VPC | `vpc-2r4i9oho5izuo4cl9ftrznbow` |
| VKE | `cdc0gtum20sprm8k132h0`, `v1.36.1-vke.7`, private API only |
| Namespace / release | `seed-mcp-staging` / `seed-mcp` |
| Mode | `apig-production`; the retained namespace name is historical |
| Source | `ed3c184c3d3baba43da3408c4a742092bc3ff074` (native TTS audio) |
| Image | `ghcr.io/byteplus-sa/seed-mcp@sha256:f976af48c53f903195e060e5b4ecea32a23456fca27490ae085296d5834c96fe` |
| Helm / Deployment | Revision 6 / generation 7 |
| Replicas | Two Ready, zero restarts, on distinct workers `10.80.0.147` and `10.80.0.152` |
| Application Service | Private ClusterIP, TCP 8443, no session affinity |
| State / uploads | `STATE_BACKEND=none`, no PVC/database, temporary uploads disabled |
| Provider credentials | Client-side headers only; absent from application environment |
| Scaling | HPA 2-6; two fixed baseline workers, optional burst pool 0-2 |
| Private metrics | Disabled; `/metrics` and `/ready` are not public |

The November 27 rollout used one burst worker and then automatically returned to
the two baseline workers (`10.80.0.146`, `10.80.0.147`). No manual node or
autoscaler change was made. Final node count was two at 08:19 UTC.
The baseline workers share an AZ; hostname spreading is not AZ resilience.
Baseline, gateway and networking charges continue at idle.

| APIG object | ID / state |
| --- | --- |
| Gateway | `gdc0lvqennrmdh5hbe8kg` |
| HTTPS service | `st63a28rvt0o3d9htd28d` |
| Private application upstream | `udc15lgippshdkifdom6g` |
| Public health route | `rdc4jub9huhn5qi7l8r20`, enabled, exact `/health` |
| Public MCP route | `rdc4jub9huhn5qi7l8r2g`, enabled, exact `/mcp` |
| Earlier operator-only/diagnostic routes | All three retained disabled |

Logging and tracing read back disabled. Routes have no active retry, rewrite,
header modification, mirror or fallback policy. Disabled APIG response timeout
means no route timeout; application/client/grace limits remain in force.
Ingress remains limited to `10.80.48.0/20` and `10.80.64.0/20`.
No public CLB replacement, hosted database, execution journal or server budget
ledger was introduced.

## Native TTS Update

On November 28, the operator selected direct audio instead of TOS downloads
and a 30 MiB decoded-audio limit. HTTP now exposes eight baseline tools.
`seed_tts_generate` returns one native MCP audio block plus metadata, with no
TOS credentials, output bucket, feature flag or download URL. Other media tools
retain their existing provider-URL delivery. Stdio persistence remains intact.

- [Exact-head CI](https://github.com/byteplus-sa/seed-mcp/actions/runs/46123945896)
  and image digest verification passed.
- [Protected check](https://github.com/byteplus-sa/seed-mcp/actions/runs/46124606000)
  and [one-shot rollout](https://github.com/byteplus-sa/seed-mcp/actions/runs/46124895457)
  passed on different fresh ephemeral runners. Runner registrations, Pods,
  ConfigMaps and registration Secrets were removed; readiness is false again.
- Public H1/H2 health, eight-tool inventory, TTS discovery and its 30 MiB
  (31,457,280-byte)
  limit passed. Anonymous TTS/image calls were rejected, Authorization remained
  rejected, and private routes remained 404. A real FastMCP client verified discovery.
- Both final replicas use the verified image, `STATE_BACKEND=none`, no PVC,
  no operator generation/storage credentials, and disabled temporary uploads.
  A burst worker was used during rollout, but the verified 08:19 UTC snapshot
  was back at two Ready replicas. Subsequent scale events were not revalidated
  in this update.
- Local validation passed 3,567 Python/Helm tests (20 skipped), 79 documentation
  tests, and mock-only HTTPS/drain checks. The full 30 MiB audio response passed
  through local Caddy and a FastMCP client; one byte over the limit was rejected.
- After separate explicit approval and dependency checks, the unused
  `seed-mcp-tts-output-3000006864-20261128` bucket,
  `seed-mcp-tts-output-20261128` IAM user and `SeedMcpTtsOutput20261128` policy
  were deleted and confirmed absent. The bucket was empty, no runtime keys
  existed, and no TTS Kubernetes output Secret had been created.

**No paid synthesis was performed for this update.** Maximum-size delivery
through public APIG, concurrent maximum-size production capacity, IDE playback/
saving, voice entitlement and audio quality remain unverified. A 30 MiB audio
block is 40 MiB Base64 before metadata. A lost response has no recovery API;
do not automatically repeat synthesis.

## Delivery Evidence

- [PR #14](https://github.com/byteplus-sa/seed-mcp/pull/14) introduced protected
  production mode, private H1 and the scoped waiver documentation.
  Its [check](https://github.com/byteplus-sa/seed-mcp/actions/runs/45955856779)
  and [deployment](https://github.com/byteplus-sa/seed-mcp/actions/runs/45956483339)
  succeeded before public launch.
- [PR #15](https://github.com/byteplus-sa/seed-mcp/pull/15) corrected rollout
  placement with revision-scoped topology spreading. Independent exact-head QA
  found no actionable issues. PR CI and main image publication passed.
- Final [protected check](https://github.com/byteplus-sa/seed-mcp/actions/runs/45961326022)
  and [one-shot deployment](https://github.com/byteplus-sa/seed-mcp/actions/runs/45961913681)
  succeeded on different ephemeral runners. Both environments remained
  main-only with reviewer approval and no administrator bypass.
- Final runner registrations, Pods, registration Secrets and private scratch
  were removed. `VKE_PRODUCTION_RUNNER_READY=false`; another delivery requires
  a fresh verified runner. No automatic Helm retry or rollback occurred.
- The corrected rollout maintained two available replicas in every sample.
  Subsequent automatic scale-in maintained at least one available replica.
  Final placement was split across baseline workers without manual rebalance.

## Acceptance Evidence

The following paid-provider and launch evidence is from November 27, not the
native TTS update above.

The operator explicitly approved bounded real tests with client-side keys,
an aggregate US$5 ceiling, and public launch after the gates passed.
Uploads stayed disabled.

| Check | Observed result |
| --- | --- |
| Live APIG/VKE drain | Two 590-second accepted mock calls completed over public H1 and H2, one dispatch each, with complete task/request receipts |
| Intake withdrawal | Ready endpoint withdrawn within the 0.252-second observation; new request returned 503 |
| Graceful exits | App and Caddy exited 0 within 590 seconds after TERM; no force-kill counted as success |
| Mock isolation | No outbound socket violation, no real provider calls, no production pod termination; all temporary gateway/Kubernetes objects removed |
| Certificates | Both final baseline replicas served the expected certificate; direct TLS validation and health passed; H2-capable private offers negotiated H1 |
| Seedream | One 1K PNG from `dola-seedream-5-5-261028`; HTTPS byte delivery verified |
| Seedance | One four-second 480p request on regular 2.5 using the generated image as first-frame reference; task succeeded and MP4 delivery verified |
| Seed Audio | One MP3 on `seed-audio-1.0`; reported duration and billing duration 2.70845 seconds; HTTPS byte delivery verified |
| Task lifecycle | Exact-ID get/list, same provider key with different client secret, invalid-key rejection and deletion of the test's own terminal task passed |
| Public launch | Marker-free H1/H2 health and seven-tool discovery passed, as did a real FastMCP client |
| Public boundaries | Credential-free generation and incoming Authorization, including empty values, rejected; private paths stayed 404 |

There were exactly three paid create dispatches, with no automatic resubmission.
The client reserved US$4 conservatively against the approved US$5 test limit;
**that reservation is not a settled bill**. Image/video preview estimates were
US$0.03/US$0.35 and are built-in estimates, not account quotes. Provider settlement
and a complete matched infrastructure bill were not established by these tests.
No keys or signed media URLs are included in this record.

The live drain worker used an isolated copy of the earlier published runtime.
Application, dependency, Dockerfile and proxy source were unchanged by PR #15;
that equivalence was checked. This tests live APIG/VKE termination with mocked
provider work, not every real-provider failure or node-failure scenario.
Real paid tests used the final deployed image through the FastMCP client.
Model-driven Codex/Claude sessions, disabled upload workflows, every model/
variation, full capacity and visual/audio quality were not certified.
The service does not promise durable replay, crash recovery or exactly-once billing.

### Native TRAE Client Acceptance

On November 27, 2026, at 11:44-11:47 UTC, the operator separately approved
three additional paid tests with a US$5 test budget. These calls used the
actual TRAE session's user-level `seed-mcp-remote` connection to the public
endpoint above, not the earlier Python FastMCP test client or the retained
local `ark-mcp` connection.

The native preflight reported valid configuration with no issues. Provider
keys and an independent client secret were supplied through client headers,
never tool arguments. Image/video dry runs had already passed. The live
calls then established successful provider authorization for these specific
models and requests:

| Native call | Observed result |
| --- | --- |
| `seedream_generate_image` | One Seedream 5.5 PNG, 1024x1024, 1,189,301 downloaded bytes; 4,096 reported total tokens |
| `seedance_create_task` | One regular Seedance 2.5 task, `cgt-20261127194458-57c0z`, accepted once and succeeded; requested four seconds at 480p without audio |
| `gen_task_get` | Same accepted task polled to terminal success; downloaded H.264 MP4 is 854x480, 4.041667 seconds, 1,019,337 bytes, without an audio stream |
| `gen_task_list` | Exact-ID filtered result matched the succeeded task; unchanged-filter cursor pagination ended with an empty page and null cursor |
| `seed_audio_generate` | One Seed Audio 1.0 MP3, 30,137 bytes, stereo 44.1 kHz; provider generation/billing duration 1.80045 seconds, container duration 1.828571 seconds |

All three media URLs were downloaded client-side with HTTPS certificate
verification and without forwarding provider-key headers. Each full file
passed FFprobe inspection and FFmpeg decoding. The video reported 38,830
total tokens. There were exactly three new create calls and no automatic
resubmissions. The successful video task was retained; cancellation/deletion
was not part of this native-client batch.

This establishes working native TRAE-to-remote image, video, audio and task
read workflows for the tested configuration. It is not certification of all
TRAE versions, other clients, all model features or subjective media quality.
The additional US$5 approval is not an enforced provider spend cap or a
settled charge; account billing remains unverified. No credentials, signed
URLs or generated media are committed with this evidence.

## Renewal and Follow-Ups

Owner: `arthur.lechoncito`.

| Item | Expiry / action |
| --- | --- |
| Backend certificate Secret | `seed-mcp-backend-tls-20261126` |
| Certificate fingerprint | `9e93617ade7469d3b527e938b9b29b881f8f0a5674b2ee8cedde4fb8a78feb03` |
| Certificate expiry | `2027-02-24T00:23:58Z`; renew by `2027-01-25T00:23:58Z` |
| Registry credential | Verified operator-owned classic PAT, exactly `read:packages`; expires `2027-02-25T06:11:58Z` |
| Registry renewal | Review alongside the certificate by January 25; preserve replacement-only pull verification |

The earlier exposed registry token was revoked and rejected with HTTP 401.
Replacement-only pulls and credential-free negative controls passed on both
baseline workers; overlap was 67.733 seconds, below the approved 15 minutes.
The active Kubernetes pull Secret was updated in place.

No automatic certificate issuer, reload controller or expiry notification was
installed. Follow [certificate renewal](backend-certificate-renewal.md), use
versioned Secrets, and verify every replica after a protected rollout.
The separate GitHub Pages deployment failure and later billing reconciliation
remain maintenance follow-ups, not evidence that this MCP endpoint is closed.

## Historical Record

The completed implementation plan was removed from `plans/`. Its immutable
[execution history](https://github.com/byteplus-sa/seed-mcp/blob/0b60ea03aa98726b7b71c99abc697ae768504469/plans/PLAN_GATEWAY_DEPLOYMENT.md)
retains the preparation, failed-attempt reconciliation, operator approvals,
research sources and historical validation evidence.

The final deployment uses dedicated fresh Terraform state. Before provisioning,
the operator separately approved retirement of the audited demo VPC
`vpc-14wd8di3kiku83tvs80ksgahc` and release of exactly
`eip-q6j8mo4nqsjk1ntgtrsxgwcx` and `eip-14wmwikupd7uo3tvs80xws8n3`.
Dependency checks and absence readbacks were recorded separately; historical
audit/ownership limits were not retroactively resolved. These completed actions
do not authorize further unrelated cleanup or reuse.

The durable contract is [VKE deployment](../specs/SPEC_VKE_DEPLOYMENT.md);
delivery procedures are in [GitHub Actions deployment](github-actions-deployment.md).
Fresh provisioning, credential changes and future releases need their own
reconciliation and authorization, not replay of historical mutation commands.
