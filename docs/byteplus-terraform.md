# Deploy on BytePlus with Terraform

This starter targets one Ubuntu 24.04 AMD64 ECS host, TLS ingress and retained
SQLite state for the [HTTP BYOK foundation](../specs/SPEC_HOSTED_BYOK.md).
It does not implement PostgreSQL, HA, multi-replica coordination or public
launch readiness. Infrastructure operations incur charges and require explicit
operator approval. This documentation update provisions nothing.

## Validation Status

The prior 2026-11-13 infrastructure test was partial: EIP quota blocked it
before application activation. Partial Terraform state was preserved; the
temporary VM, both disks and security group were subsequently removed.
That evidence does not validate the new BYOK application. HTTPS/client checks,
interruption/resume and application-only updates are not yet certified live
for this foundation. Offline tests are not deployment certification.

## Requirements

Members connecting to an existing server do not need IAM credentials,
Terraform, Python or a checkout. They need their provider key, a client-generated
isolation secret and a trusted HTTPS endpoint. See
[client setup](setup/shared-server.md).

Operators need:

- A trusted macOS/Linux workstation; native Windows deployment CLI support is
  not established. Use Git or a reviewed source archive of this fork.
- Python 3.12+, uv and Terraform `>=1.9,<2.0`, plus the locked provider.
- Scoped infrastructure IAM/STS credentials, account quota and a registered
  regional SSH public key pair; working ECS Cloud Assistant is required.
- A verified digest-pinned Linux AMD64 image implementing `MCP_AUTH_MODE=byok`.
  No Seed MCP image publication is assumed. Upstream images are not proof of
  BYOK support.
- A private deployment workspace, encrypted storage and tested off-host backups.

ArkCLI and bytedcli are not required. Docker/Compose are installed on the VM
by bootstrap, not required on the operator workstation. Node/npm are only
needed to develop the docs site.

## Set Up Dependencies

Use your organization's approved installation process or the official
[uv installation guide](https://docs.astral.sh/uv/getting-started/installation/),
[Python setup](https://docs.astral.sh/uv/guides/install-python/) and
[Terraform installation guide](https://developer.hashicorp.com/terraform/install).
Review downloaded code before executing it.

From a reviewed checkout:

```bash
uv python install 3.12
uv sync --locked --no-dev --python 3.12
terraform version
uv run --no-sync python scripts/deploy_byteplus.py --help
```

These commands prepare dependencies/show help; they do not authorize an apply.
Use the checked-in Terraform provider lockfile; never bypass checksum checks.

## Set Up IAM and Credentials

Infrastructure credentials (`BYTEPLUS_ACCESS_KEY`, `BYTEPLUS_SECRET_KEY`,
and matching `BYTEPLUS_SESSION_TOKEN` for STS) belong only in the operator's
approved secure injector. Never put values in HCL, tfvars, CLI arguments,
shell history or logs. ArkCLI sign-in does not automatically configure them.

Review Cloud Control and underlying ECS/EBS/VPC/EIP permissions, plus
`DescribeImages`, `DescribeKeyPairs`, `DescribeInstances`, `RunCommand` and
`DescribeInvocationResults`. Guest commands run as root. This is a capability
checklist, **not a validated least-privilege IAM policy**. The CLI does not
create IAM users or grant itself access. Refreshing STS between plan and apply
requires a new plan.

Official account setup references:

- [Create IAM access keys](https://docs.byteplus.com/en/docs/IAM/creating-an-access-key)
- [IAM roles](https://docs.byteplus.com/en/docs/IAM/about-roles)
- [Temporary STS credentials](https://docs.byteplus.com/en/docs/byteplus-platform/reference-assumerole)
- [ECS key pairs](https://docs.byteplus.com/en/docs/ecs/Creating-key-pairs)
- [Cloud Assistant](https://docs.byteplus.com/en/docs/ecs/Install-the-Cloud-Assistant-client)
- [GHCR pull authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

A private image needs a protected pull token with `read:packages`, not write
permissions. Keep token files mode `0600` in a private `0700` directory.
Do not print a token or upload credentials merely to inspect status.

## Guided Deployment CLI

Review the selected checkout's `scripts/deploy_byteplus.py --help` and
deployment templates before use. Only a fresh BYOK deployment is in scope;
no old-auth compatibility migration or existing-resource adoption is supplied.
Do not mix raw `terraform apply`, manual disk initialization or credential
generation into a CLI-managed deployment.

The runtime receives operator `MCP_IDENTITY_HMAC_KEY` (32 random bytes,
64 lowercase hex) and positive `MCP_IDENTITY_KEY_VERSION` (default `1`).
It receives **no customer provider keys**. The HMAC key is not a customer
credential or connection token. [Provider-secret sync is superseded](secret-manager.md).
Do not use retired provider-bundle or hosted job-snapshot workflows.

HTTP defaults are 60 RPM, 2 MiB request bodies, 64 in-flight requests and
`STATE_MAX_RECORDS=100000`; keep these limits positive. HTTP has no jobs,
native tasks, object storage/artifact tools or resources. Provider origins
are fixed official URLs and readiness makes no provider probes.

The CLI's saved approvals and invocation IDs concern infrastructure actions,
not provider inference idempotency. Unknown guest-command acceptance requires
reconciliation; do not erase journals or regenerate identity secrets to force
a retry. Preserve stable HMAC settings during image updates.

## State and Activation

Keep one application instance and a fresh private SQLite database. The retained
mount contains ownership/budgets and protected runtime configuration. The
application's default container state path is `/app/.artifacts/runtime.sqlite3`;
the directory name does not enable HTTP artifact persistence.

Verify disk identity, filesystem UUID and mount before activation. Never
format a recovered disk or the system disk. Protect configuration mode `0600`
and reject symlinks; do not source dotenv files or dump rendered configuration.
Only TLS ingress should publish network ports. Configure Host/Origin allowlists
and distrust forwarded IP headers unless the proxy overwrites them.

## Verify Before Inviting Users

Check minimal `/health` and `/ready`, anonymous static discovery, exactly 9
HTTP tools (12 with OmniHuman), no resources/jobs/native tasks and no public
`/metrics`. Verify missing selected credentials fail and another client secret
cannot poll/cancel a known task. Dry runs still need the selected provider key
and client secret; they do not prove provider authentication or entitlement.

Validate actual Codex/Claude or other target client header handling separately.
Any live generation requires its own approved budget. Test shutdown, reboot,
backup restore and abuse/load bounds in an approved environment.

## Backup, Upgrade and Recovery

Drain active foreground work before maintenance. Preserve SQLite and matching
HMAC key/version. Credential/HMAC changes alter scope and have no recovery
bridge. Infrastructure image/bootstrap changes can plan host replacement:
review the entire Terraform plan, protect retained storage and never remove
deletion guards as an automatic workaround.

Provider acceptance followed by a lost response or failed ownership write can
remain ambiguous. SQLite HTTP asynchronous-create idempotency is implemented:
non-dry Seedance/OmniHuman calls require `idempotency_key`, and only complete
saved receipts replay with ownership checks. Same-key recovery is not polling
or automatic resume of unresolved work. Claims never auto-prune; at
`STATE_MAX_RECORDS` new keys fail while existing keys remain readable. Preserve
the state volume and matching HMAC configuration, never delete claims to
admit work. See the
[submission contract](../specs/SPEC_HOSTED_BYOK.md#http-submission-safety).
Synchronous product replay and complete crash recovery remain deferred;
PostgreSQL/Redis are future scaling choices, not initial requirements.
Do not claim exactly-once generation, multi-replica support or public-launch
readiness from an infrastructure apply.

## Decommissioning

Deletion/retention guards require deliberate review. Choose archival needs
before changing them, confirm actual cloud absence after approved deletion
and account for retained disk, EIP, snapshot and traffic charges. A clean
Terraform state alone is not proof that all cloud resources are gone.
