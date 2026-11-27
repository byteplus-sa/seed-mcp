---
title: Hosted Deployment Status
---

# Hosted Deployment Status

**Verified public on November 27, 2026, at 08:28 UTC.** This is a point-in-time
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
| Source | `0b60ea03aa98726b7b71c99abc697ae768504469` (PR #15) |
| Image | `ghcr.io/byteplus-sa/seed-mcp@sha256:d6cfd78c0b8802caefd8baf132c2039ea155a12bd228c2009b9fa10e19331228` |
| Helm / Deployment | Revision 4 / generation 5 |
| Replicas | Two Ready, zero restarts, one on each baseline worker |
| Application Service | Private ClusterIP, TCP 8443, no session affinity |
| State / uploads | `STATE_BACKEND=none`, no PVC/database, temporary uploads disabled |
| Provider credentials | Client-side headers only; absent from application environment |
| Scaling | HPA 2-6; two fixed baseline workers, optional burst pool 0-2 |
| Private metrics | Disabled; `/metrics` and `/ready` are not public |

The final rollout used one burst worker and then automatically returned to
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

## Staging Delivery Retirement

On November 28, 2026, the operator authorized production-only delivery cleanup
and publication to main. Complete GitHub inventories found eleven completed
delivery runs, no active delivery, and zero registered private runners.
The two latest completed runs were the subsequent
[check](https://github.com/byteplus-sa/seed-mcp/actions/runs/46010530376)
and [delivery](https://github.com/byteplus-sa/seed-mcp/actions/runs/46011152742)
for source `7a693e47864793fc76c18edb4f1ab6c48cc2b71a`.
This run inventory is not a fresh cluster inspection; the earlier live-instance
and acceptance evidence above remains a dated record.

Verified GitHub quarantine:

- `byteplus-staging` now has exactly one variable:
  `VKE_PREREQUISITES_CONFIRMED=false`. Its ten deployment references were removed.
- Its reviewer/main-only/no-administrator-bypass protections remain unchanged.
  The protected environment itself was not deleted.
- Production environment variables and both environments' protection policies
  matched pre-change readbacks. Production enablement and the shared restricted
  runner group were preserved; production runner readiness remains false.
- The workflow source accepts only production and keeps the same path, job IDs,
  runner allowlist and `byteplus-staging-delivery` concurrency key.
  The live namespace `seed-mcp-staging` and release `seed-mcp` are not renamed.

The repository's legacy `VKE_RUNNER_READY=false` remains an explicit deny
value for historical runs. Its obsolete `VKE_RUNNER_GROUP` pointer is removable
only once the production-only source is on main; removing that pointer must not
delete the shared group or the production pointer.

**Final GitHub environment deletion remains pending.** The conservative
30-day boundary from the latest pre-cutover run's original creation time is
after **2026-12-27 13:54:29 UTC**. Refresh all paginated inventories and verify no
legacy attempts remain active, waiting or queued before any approved deletion;
this date is not an automatic deletion schedule.
Old delivery-only reruns can reuse configuration-job outputs, so preserve the
disabled prerequisite and environment protections throughout the window.

No application rollout, Kubernetes/cloud resource mutation, credential change,
private-file deletion or paid provider call was performed for this quarantine.
See the [retirement runbook](github-actions-deployment.md#legacy-staging-retirement).

## Acceptance Evidence

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
