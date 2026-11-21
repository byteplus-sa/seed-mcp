---
name: ark-mcp-setup
description: Set up or update Seed MCP in Claude, Codex, TRAE or another client. Use for local stdio installation or a trusted HTTP BYOK connection with private credential entry.
---

# Ark MCP Setup

This project-local skill installs the narrowed Seed MCP fork from
`byteplus-sa/seed-mcp`. Package, module, tool and skill names remain unchanged.
Upstream Ark MCP documentation is retained-tool detail only, not an
installation or release source for this fork. No Seed MCP Pages deployment
or release is assumed.

Install the server into the user's preferred MCP client, not the client
application itself. Use this skill for onboarding, updates, registration,
and credential-file setup. Use `ark-mcp` for generating media.
Do not install an editor or CLI, change the agent's model provider, or deploy
public HTTP as a side effect.

Read [platforms.md](references/platforms.md) before selecting paths or running
commands. This skill must work independently of its author's device or a
repository checkout. Resolve the current user's home, OS, shell, installed
tools, and execution host each time; never reuse paths or account settings
from a previous session.

## 1. Resolve the Client and Scope

1. Prefer the user's named client over detection. Otherwise use explicit
   runtime host metadata to identify the current agent. Distinguish the
   hosting IDE from an embedded agent: Codex inside TRAE might mean either.
2. Use executable availability and config-directory existence only as
   supporting evidence, never proof of the active agent. Do not dump the
   environment, process arguments, or configuration files to identify it.
3. If ambiguous, ask one short question with the likely clients. Distinguish
   Claude Code from Claude Desktop, and TRAE IDE from TRAE Work and CN from
   International. Never configure every installed client automatically.
4. Default to **global/user-level MCP registration**. State the detected
   client, the evidence, and the default before making changes; honor an
   explicit project/local preference without asking again. If project scope
   is requested, resolve the intended workspace, not this skill's directory.
5. Confirm where the server actually runs: local OS, WSL, SSH host, container,
   or cloud sandbox. Commands, paths, credentials, and client registration
   must refer to the same runtime. A local path cannot configure a remote
   sandbox. Ask before copying credentials to another machine.

Read [clients.md](references/clients.md) for the selected client only.
Global MCP registration is separate from installing this skill globally.
Create or distribute skills through the host's skill installer only when
requested; changing MCP scope does not authorize changes to all skill roots.

If the user supplies an existing trusted HTTP endpoint, skip local installation,
release staging and local server credential files. Follow the HTTP BYOK branch
in [clients.md](references/clients.md#http-byok) and
[credentials.md](references/credentials.md#http-client-credentials).
The optional `scripts/configure_http_client.py` helper in a reviewed checkout
prints stdout-only Codex/Claude snippets with environment-name references.
It reads no files or environment secret values, writes no configuration,
makes no network calls and invokes no client. It is not an installer;
registration still needs the user's chosen scope and permission.
Do not deploy a server as a side effect. Ask which transport if unresolved.

Hosted operators use the selected checkout's `docs/byteplus-terraform.md`
and `specs/SPEC_VKE_DEPLOYMENT.md`: dedicated VKE replaces ECS/Compose.
Do not offer retired helpers. The stateless Deployment uses same-pod Caddy,
default 2-6 pod HPA, PDB and hostname spread on maintained Kubernetes >=1.30.
No state PVC/StorageClass/headless Service renders; Redis is not required.
Terraform uses dedicated fresh state and stores no HMAC/
TLS Secret/kubeconfig. Helm references existing Secrets only. Private API
access requires operator private connectivity.

Optional `public_gateway_enabled` Terraform preparation defaults false and
requires an explicit distinct regional secondary AZ when enabled. It creates
a dedicated standard APIG/two subnets only, not routes, a default domain or a
generic MCP endpoint. Omit partial disabled tracing configuration, which native
APIG rejects; logging and tracing must both read back disabled. A postcondition failure
may follow creation and requires inspection, never an automatic create retry.
Private HTTPS verification, stateless/no-retry routing, header/proxy trust and
full cost review remain operator responsibilities. Explicit operator approval
may allow infrastructure creation first and billing inspection afterward;
real BYOK launch still requires TLS/logging/routing acceptance. Regional quota
failures require verified headroom, not unrelated-network reuse or blind
create retries. Reconcile accepted tasks, protected state and inventory before
any fresh plan or new create attempt. The chart defaults to public CLB/Caddy;
opt-in `service.mode=apig-staging` uses private ClusterIP/ingress policy,
separate `backendHost`, credential-header refusal and disabled uploads.
This is synthetic-only, not a public client endpoint or a backend trust fix.
Keep public application routes disabled; temporary tests require verified
operator-only exact header matching at APIG and immediate disable/404 readback.
Never silently substitute CLB for a selected gateway design. Do not enable gateway infrastructure
as a client-setup side effect.

The optional `deploy-vke.yml` GitHub Actions workflow supplies manual main-only
Helm delivery through protected `byteplus-staging` approval and a workflow-
restricted private runner group. A same-VPC runner needs no laptop VPN/CEN;
ordinary GitHub-hosted runners do not gain private API reachability from keys.
Read `docs/github-actions-deployment.md` in the selected checkout for bootstrap,
isolation, existing kubeconfig/Secrets and nonsecret reference variables.
It does not provision VKE, establish GitHub IAM/OIDC federation, synchronize
Secrets or install addons. Do not enable runner/prerequisite acknowledgements
until verified or run deployment as a client-onboarding side effect.

Terraform defaults to two fixed private on-demand baseline nodes, with
`burst_node_max_count=0` disabling extra workers. An approved positive maximum
adds a separate pool starting/minimum at zero; baseline plus burst is bounded
to ten nodes. Only the burst live desired count is ignored by Terraform.
VKE administrators own compatible Cluster Autoscaler installation, discovery,
automatic scale-in and drain settings; HPA alone does not scale nodes. Verify
pending-pod scale-out, safe burst return to zero and drain timeout above the
configured pod grace (660 seconds by default). Baseline/network/cluster charges
remain at idle; node bounds are not a spend cap. Do not enable burst, install
addons or apply resources as a side effect of client setup.

Helm provides `models.seedream`/`models.seedance` `defaultModel` and verified
`{model_id, family}` binding lists, with strict families and default inclusion.
Alternate defaults require bindings. This does not verify lineage or permit
arbitrary endpoint headers: explicit tool `model` wins and exact registry
matching remains required. No arbitrary env or provider-secret map is accepted.
Chart `app.dailyBudgetUsd=0` is required: no HTTP budget ledger exists.
Provider/owner concurrency is5/3 per pod; burst0 inherits RPM.

Optional `temporaryUpload.enabled`/`existingSecret` add HTTP-only
`media_prepare_upload`, with restricted operator TOS signing credentials and
an enrolled client-secret digest allowlist. The existing upload Secret must
differ from identity/TLS. No raw secrets belong in values or Terraform.
Bucket privacy, disabled versioning, prefix IAM, CORS, lifecycle and
storage/egress controls need separate operator setup; do not enable as a
side effect of client onboarding. See `docs/temporary-uploads.md` in the checkout.

TOS mode defaults to static credentials. Explicit
`temporaryUpload.credentialsMode=irsa` requires separately verified regional
VKE OIDC, exact issuer/audience/namespace/ServiceAccount trust and prefix-only
TOS IAM. It creates an app-only manual OIDC projection with audience
`sts.volcengine.com`, not IAM roles, cluster enablement or webhook injection.
The upload Secret then contains configuration/enrollment only, no AK/SK/token
references. Runtime refresh is lazy, single-flight and memory-only; static
fallback is rejected. Default 3600-second STS credentials can shorten nominal
24-hour GET URLs to an hour or less; refresh never renews issued URLs.
Live OIDC endpoint acceptance/readability/rotation remain staging gates.
Never enable cluster IRSA or change IAM as a side effect of setup.

`cloud-controller-manager` and addon lifecycle are VKE-admin owned outside
Terraform/Helm. Inspect existing installations; install absent compatible
maintained versions via VKE addon management. CCM Running and Ready nodes,
metrics API and capacity checks must precede
`prerequisitesConfirmed=true`; acknowledgement is not readiness proof.
CSI is not a stateless app prerequisite; no application volumes are provisioned.
This is operator deployment work, not part of customer connection setup.
Historical database compatibility and stateful-release migrations are not
supported. Source deletion is not cloud decommissioning. Never automatically
requeue uncertain provider submissions.

## 2. Resolve an Installation

- Default upstream: `https://github.com/byteplus-sa/seed-mcp.git`.
  Check existing origins against that repository; accept its equivalent
  GitHub SSH URL. Ask before using a fork or a different remote. Never put
  access tokens in Git URLs or shell arguments.
- Reuse a verified existing installation only when appropriate. Prefer a
  dedicated managed checkout instead of modifying the user's development
  branch. Do not overwrite dirty, divergent, or unrelated working trees.
- Resolve the managed root using [platforms.md](references/platforms.md),
  honoring user paths and platform-managed locations. Use versioned checkout
  directories under `releases/`, keeping the previous working version
  available for rollback.
- Project scope controls visibility, not credential sharing. It may reuse a
  managed checkout outside the project. Isolate runtime state and credentials
  separately when the user needs independent installations.
- Check `git`, `uv`, and the selected release's Python requirement. Use its
  `pyproject.toml` and `uv.lock`, not a version memorized in this skill.
  Obtain approval before installing missing system tooling. Do not use sudo
  or unreviewed curl-to-shell installation as an automatic fallback.

## 3. Select and Stage the Latest Stable Release

Read [releases.md](references/releases.md) before downloading or updating.
Resolve the latest published non-draft, non-prerelease GitHub release at
execution time, then record its tag and resolved commit SHA.

If no stable release exists, ask whether to use the current default-branch
commit, select an explicit ref, or stop. A network/authentication failure is
not evidence that no releases exist. Never silently fall back to `main`.

Stage the selected commit in a new managed checkout, detached from any
development branch. Inspect its setup instructions and migration notes
before executing downloaded code. The capability narrowing is breaking:
export needed old 3D outputs with the old server before upgrading; its saved
3D artifacts are not served by the narrowed schema. Do not promise state
compatibility or automatic migration. In the staged directory run:

```bash
uv sync --locked --no-dev
```

Do not upgrade dependencies independently or rewrite `uv.lock`. Use absolute
paths and an argument array in client configuration. Keep the prior version
and MCP entry until the staged version passes verification.

## 4. Prepare Private Credential Entry (Local stdio)

Read [credentials.md](references/credentials.md) before handling credentials.

1. Ask which capabilities are needed if unspecified. ModelArk and Seed Speech use different credentials; never assume one key
   unlocks everything. Keep whitelist and destructive-operation flags off.
2. Create a minimal blank `.env` in a private directory outside the checkout,
   with owner-only access. Preserve an existing file without reading or
   overwriting its values.
3. **Open the file in a local, non-AI text editor** using a native opener or
   the user's chosen editor. Ask the user to enter keys, save, and confirm
   completion. Never ask them to paste credentials into chat.
4. Do not read back, screenshot, diff, upload, or index the populated file.
   Verification may load it inside the server process, but must return only
   sanitized status, field names, and enabled capability names.
5. Set `ARK_MCP_ENV_FILE` to the absolute credential-file path in the MCP
   entry. Store no credential values in the entry.

Permissions protect against other ordinary OS users, not an agent or process
running as the same user. Explain that `.env` is plaintext, not a secrets
vault. Do not promise the agent technically cannot access the file.

## 5. Register Without Damaging Existing Configuration

Use the selected client's supported CLI or configuration UI where possible;
verify local `--help` before relying on CLI flags. Follow
[clients.md](references/clients.md).

- Default server name: `ark-seed`. Inspect only non-secret metadata for that
  name, including scope and command path, plus possible shadowing entries.
- If the name belongs to another server, ask before replacing it. If it is
  the intended installation, update only that entry after staging succeeds.
- Make an owner-only backup before mutation. Client configurations can
  contain unrelated tokens: never print the full file or full diff, and
  preserve permissions on backups.
- Parse JSON/TOML using an appropriate parser; preserve unrelated fields and
  comments with a format-aware edit. Never use regex-based whole-file
  rewrites. Detect concurrent changes and stop rather than overwrite them.
- Global is the default, not permission to override an explicit project
  choice. If the client does not support that scope, explain and ask.
- Do not delete lower/higher-scope entries to resolve shadowing without
  consent. Project-local config with absolute machine paths should not be
  committed automatically.

Use this launch contract, adapting only the client's envelope:

```json
{
  "command": "/absolute/path/to/uv",
  "args": [
    "--directory", "/absolute/path/to/managed/checkout",
    "run", "--locked", "--no-sync", "python", "-m", "ark_mcp"
  ],
  "env": {
    "ARK_MCP_ENV_FILE": "/absolute/path/to/private/.env",
    "MCP_TRANSPORT": "stdio",
    "MCP_AUTH_MODE": "local"
  }
}
```

Resolve the `uv` executable on the server host. Do not rely on shell expansion
of `~`, `$HOME`, or `${workspaceFolder}` inside arbitrary client JSON.
The launch contract requires the successful locked sync above.

## 6. Verify and Finish

1. Check credential-file ownership/permissions and config syntax without
   displaying values. Validate settings with exception text suppressed;
   report only invalid field names, never Pydantic input values.
2. Launch the staged server with the exact command, args, environment, and
   intended credential file using an MCP client. Initialize, list tools,
   read `seed-health://status`, and call `ark_list_models` with
   `{"input": {}}` (verify the selected release's schema). Do not run paid
   generation or uploads for setup verification. For this standalone
   preflight process only, set `ARTIFACT_DIR` to a private temporary
   directory, `ARTIFACT_BACKEND=filesystem`, and
   `READINESS_CHECK_PROVIDERS=false`. Keep active local/remote state and
   optional provider probes out of preflight; do not persist these
   overrides into the user's MCP entry.
3. Ensure the requested product tools register; zero provider credentials
   can produce a healthy server with no generation tools. Tool registration
   proves configuration loading, not provider authentication or entitlement.
4. Ask before interrupting active calls or restarting the user's client.
   Provider work can continue after disconnect; retain task/request IDs. Reload/restart MCP and
   verify discovery from the actual target agent when that interface is
   available. Otherwise report that target-client verification is pending.
5. On failure, leave the old installation active. If registration already
   changed, restore only the affected entry from the protected backup,
   checking for concurrent edits first. Never roll back credentials blindly.
6. Report the client and scope, tag/SHA, checkout path, credential-file path
   only, verification results, restart needs, and any unresolved setup.
   Do not say "installed successfully" when a UI step or credential entry
   is still pending.

For repeat runs, keep an already-current installation unchanged unless repair
is needed. Preserve credentials and user-selected flags during updates.

Both transports execute directly and reject explicit native task opt-in.
Local stdio has 12 conditional tools, four always registered, with storage
and artifacts retained. Configure client timeout 660 seconds for the default
600-second cooperative tool deadline. Admission defaults to 2 seconds,
owner-first then provider; operator maxima are 30 seconds for admission and
3600 for the whole tool. SDK/SQLite draining may exceed the deadline.
Timeout does not cancel provider work: retain safe accepted IDs and never
blindly resubmit. Local outputs use live MCP roots or `OUTPUT_ROOTS`.

For HTTP, verify default anonymous/static `ark_list_models` with
`{"input":{}}` and `connection=null`, and 7 tools,
or 8 when temporary upload preparation is enabled,
no resources, no job tools/native tasks and direct foreground execution.
Then optionally call `{"input":{"check_connection":true}}` on live HTTP:
only ModelArk image/video header presence and exact endpoint defaults are
checked. Omit `kind` for both routes or select `"image"` / `"video"`;
Other kinds and stdio checks are rejected.
Missing headers return `missing_modelark_key` / `missing_client_secret`.
HTTP 400 `CREDENTIAL_REUSE` rejects a client secret equal to any supplied
provider key before tool execution. Generate an independent 32-random-byte
secret as 64 lowercase hex and update only its protected client entry, keeping
provider keys unchanged. Temporary uploads require enrollment of the replacement
digest; never expose the raw secret.
`configuration_valid=true` requires both headers and every checked route;
`authentication_verified` and `provider_calls_made` always stay false.
This does not prove authentication, endpoint existence/current lineage,
activation, entitlement, balance or reachability. Unknown IDs are not echoed;
`endpoint_not_configured` means the operator must verify and bind the exact
product ID. Explicit create-tool `model` wins over endpoint headers.
Official GetEndpoint body and OpenAPI require AK/SK signing, not ModelArk
Bearer auth; never ask for customer ModelArk AK/SK or imply arbitrary BYOE self-service is done.
See `specs/SPEC_HOSTED_BYOK.md#byoe-endpoint-authority` in the selected checkout.
Dry runs still
require the selected provider header plus client secret and are optional;
never use a billable call for setup without explicit approval.

Actual model-driven Codex/Claude tool execution and paid provider validation
remain pending. Isolated config inspection and mocked-network smoke do not
prove those paths. Do not treat an unapproved Claude project configuration
as a successful connection or change trust settings to claim validation.

Upload preparation requires a privately configured operator-enrolled client
secret, not merely any well-formed secret or provider key. No generation key
is needed for preparation, but generation still requires it. A client attachment
does not upload automatically: an HTTP multipart-capable integration must
upload directly to TOS and wait for success before using the signed GET URL.
Do not prepare/upload files for setup verification without explicit approval.

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.
Hosted HTTP is stateless and database-free. Rate and concurrency limits are per-pod.
There is no hosted replay or historical database migration workflow.
Retain accepted IDs and reconcile uncertain provider work; no automatic resubmission.
