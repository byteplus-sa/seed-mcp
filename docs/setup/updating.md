---
title: Update and Roll Back
description: Stage a reviewed Seed MCP release without overwriting credentials, active calls or development work.
---

Updating the repository does not automatically update a client connection.
The client launches the checkout or installed package recorded in its config.

## Recommended Update

For a shared server, ask its administrator to handle updates. For a local
installation, use the same terminal-capable coding agent that performed
[guided setup](install.md):

```text
Update my existing ark-seed connection for [my client].
Use https://github.com/byteplus-sa/seed-mcp, not the broader upstream server.
Read its docs/setup/manual-install.md and migration/security notes.
Select its latest stable release if available; ask before a commit fallback.
Export needed old 3D outputs with the old server before upgrading.
Preserve my keys, client settings, projects, artifacts and runtime state.
Stage and verify the update separately using discovery only.
Do not read back credentials or run paid tests.
Ask before switching the connection or restarting active calls.
Keep the previous patched installation available for rollback.
```

Review the version and any migration requirements before approving the
switch. Afterward, run the [connection check](../integrations/index.md#verify-without-paid-calls).
No separate server-start command is needed.

<details>
<summary>Manual update, activation and rollback details</summary>

## Before Updating

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.

- Finish active direct calls and save provider task/request IDs. When upgrading
  from the retired worker design, recover needed results using that old server
  before switching; the new server has no MCP job interface.
- Read [release notes](../releases.md) and applicable migration guidance.
- The narrowed schema no longer serves saved 3D artifacts. Export needed 3D
  outputs with the old server before upgrading; backups alone do not promise
  compatibility. See [breaking-capability migration](../migration-0.2.md#breaking-capability-migration).
- Preserve your private env file, client config, artifact storage and runtime
  database. Do not copy `.env.example` over existing credentials.
- Inspect the current checkout for changes. Never reset or clean a user's
  development tree as part of an upgrade.

## Stage a Patched Revision

Choose a reviewed revision containing the dependency security refresh and
the supported `fastmcp>=4.1.8,<4.2` runtime. Resolve it from the
Seed MCP fork. Do not substitute upstream Ark MCP's broader `v0.3.0`;
historical upstream `v0.2.0` is also unpatched.
Follow [release selection](manual-install.md#choose-an-installation); ask
before using a reviewed commit when no suitable release exists.

For a newer release, verify its notes, `pyproject.toml`, and `uv.lock` rather
than trusting the stable tag alone. This handbook describes the checkout,
not an assumed fork release or Pages deployment. Do not label a commit
checkout as stable.

Create a separate checkout of the selected patched revision and run
`uv sync --locked --no-dev` there. Use isolated temporary runtime and artifact
state for preflight so validation does not mutate your active installation's
database.

Verify startup and tool discovery without paid generation.
These checks do not prove key validity or provider entitlement. New env
variables and model gates should be reviewed before switching.

## Activate

Change only the `ark-seed` launch path in your client config, preserving other
servers and the existing private `ARK_MCP_ENV_FILE` path. Check that no one
edited the config concurrently.

See the database-free HTTP contract above; local stdio persistence is unchanged.

## Roll Back

See the database-free HTTP contract above; local stdio persistence is unchanged.

Restore the previous launch entry and reconnect. Keep credentials and media
unchanged. Code rollback alone is not enough if an upgrade performed an
irreversible database migration; assess backup and restoration requirements
before activation. Select a patched rollback target rather than restoring a
dependency set with known security issues.

Do not automatically delete older checkouts, backups, objects or artifacts.
For migration from the former per-model/per-operation tool surface, read
[Migrating to 0.2.0](../migration-0.2.md).

</details>
