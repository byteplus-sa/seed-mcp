# Private Credential File

The env-file workflow below is for local stdio. For a remote connection use
[HTTP client credentials](#http-client-credentials) instead.

## Location and Permissions

Resolve the private configuration directory using `platforms.md` and place
`.env` inside it. Honor only absolute, non-empty XDG overrides and use native
known-folder resolution on Windows. Keep it outside Git checkouts,
cloud-synced folders, and shared
workspaces, even for project-only MCP registration. For an isolated project
instance, use a distinct private config directory chosen with the user.

If an existing MCP entry already points to a private env file, reuse it
after checking metadata. Do not move credentials without permission.

Before creating or modifying anything:

1. Resolve an absolute path and inspect parent metadata without reading file
   contents. Reject symlinks/reparse points, unexpected owners, shared-writable
   parents, and non-regular targets. Do not chmod a symlink's target.
2. On macOS/Linux, create a new private directory with mode `0700`; create the
   file with mode `0600` and exclusive creation (`O_CREAT | O_EXCL`, with
   `O_NOFOLLOW` where available). Use a restrictive `umask` as well. Refuse
   existing files instead of truncating them. Inspect ACLs in addition to
   mode bits where supported; `chmod 600` alone may not remove ACL grants.
3. On Windows, use a local filesystem supporting ACLs. Restrict the dedicated
   directory to the current user, SYSTEM, and Administrators, remove inherited
   broad read/write grants, and verify the effective ACL with native security
   APIs or `icacls`. Use exclusive `FileMode.CreateNew` for a new file.
   Do not treat a Windows chmod result as owner-only access.
4. If permissions cannot be established, stop before credential entry.
   Do not use sudo, change broad home-directory permissions, or weaken ACLs.
5. For an existing regular file, leave its contents untouched. Ask before
   repairing unsafe permissions or replacing another user's file.

Only write blank values before the user enters secrets. Include just the
requested products. This is a template, not a populated credential file:

```dotenv
BYTEPLUS_MODELARK_API_KEY=
BYTEPLUS_SEED_SPEECH_API_KEY=
```

Omit unneeded fields. ModelArk covers image/video generation;
Seed Speech covers audio generation. Derive additional storage
credential names from the selected release's `.env.example` and docs.
Never enable optional services or object storage just because settings exist.
Native Seedance asset references require no separate management credentials.

Do not copy the entire example blindly: it may pin model IDs or enable
unrequested services. Preserve existing model bindings and region choices.
Explain that region-specific keys must match the configured provider host.

## Open for the User

Use a non-AI local text editor, or an editor explicitly chosen by the user.
Launch with a literal path argument, without shell interpolation of file
contents:

- macOS: `open -W -e "/absolute/path/to/.env"` opens TextEdit. Keep plain-text
  mode and the exact filename; do not save as RTF or append `.txt`.
- Windows: launch `notepad.exe` with the absolute file path as an argument.
- Linux: use a confirmed installed text editor. A terminal editor is suitable
  only when the user, not the agent, controls its interactive session.

Avoid opening populated credentials in an AI editor buffer, browser preview,
screen capture, or shared terminal. Do not run screenshot/desktop-inspection
tools while the credential editor is open.

Tell the user: "Enter the keys locally, save this file, close the editor, and
confirm when done. Do not paste the keys here." A launched editor is not proof
that a key was entered. If no GUI or interactive terminal is available, provide
the private file path and stop at the user-entry checkpoint.

After confirmation, recheck the file's ownership, permissions/ACL, and exact
filename. Editors can replace files on save and change their permissions.
Ensure any editor backups or swap files are equally private.

## Never Expose or Execute Secrets

- Do not `cat`, preview, search, diff, screenshot, upload, or index the file
  after user entry. Do not include its contents in agent messages or prompts.
- Never `source` or execute a dotenv file. The server's dotenv loader handles
  it as data; shell-sourcing can execute arbitrary code.
- Never pass real keys via CLI flags, here-documents, shell history, generated
  launch scripts, client JSON/TOML, or environment-dump diagnostics.
- MCP configuration contains only `ARK_MCP_ENV_FILE` and non-secret launch
  settings. An inherited environment value can override `.env`; check names
  and presence only. Ask before removing old inline credentials or changing
  the launching environment. Do not claim an env-file edit fixed a key that
  is still shadowed by an inherited value.
- Keep the file out of skill assets, test fixtures, Git, and cloud sync.
  For a user-chosen path in Git, verify ignore rules before entry and explain
  the exposure risk; recommend moving outside the checkout.
- Owner-only plaintext is not encrypted storage. The server and other
  processes with the same OS identity can read it. Recommend OS credential
  storage or a secrets manager for stronger isolation, but do not claim
  this server integrates with one without implementing that integration.

## Verify Without Leaking

Settings validation must catch exceptions inside the checking process and
emit only success/failure and invalid field names. Do not let raw Pydantic
exceptions or stack traces reach agent output: they can include input values.
Do not print `Settings`, environment dictionaries, raw logs, or API responses.

Run startup preflight in isolated temporary artifact/state directories.
Disable optional provider readiness probes in that preflight process.
Inspect only the schema/status fields needed to
confirm requested services and tools; suppress raw stderr before it reaches
the conversation. Explain generic startup failure to the user and offer a
local review of private logs rather than requesting those logs in chat.

`seed-health://status` and `ark_list_models` can confirm local configuration
and tool availability. They do not validate the API key with the provider.
Do not run a billable operation to prove authentication without permission.
An empty file is not successful onboarding when generation was requested.

## HTTP Client Credentials

Optional HTTP `media_prepare_upload` authorizes only operator-enrolled client
secrets. Enrollment uses SHA-256 of the exact ASCII header value, not decoded
bytes, and does not require a generation-provider key. Do not enroll or
provision operator TOS credentials as a client-setup side effect. Raw client
secrets stay private; the operator receives only approved enrollment digests.
Issued signed fields/URLs can include STS and are sensitive bearer permissions;
never log or publish them. See `docs/temporary-uploads.md` in the checkout.

Use only an operator-approved trusted HTTPS URL. The server receives live
provider credentials but does not persist them or fall back to startup keys.
Prepare private client environment/secret-store entries for only the desired
provider headers, plus `X-MCP-Client-Secret`. Do not create a server-side
provider-key bundle or ask for `MCP_IDENTITY_HMAC_KEY`; it is operator-only.

Generate the client secret once using the OS cryptographic RNG or trusted
secret manager: exactly 32 random bytes encoded as 64 lowercase hex.
For a manual private session, `openssl rand -hex 32` produces that format.
Never run it where agent tools, shared terminals, screenshots or logs capture
the output. The user enters the generated value directly into protected client
configuration. Do not read it back or substitute an example/test value.

Map the selected `X-ModelArk-Api-Key` or `X-Seed-Speech-Api-Key`, plus
the required `X-MCP-Client-Secret`, to private environment entries
as supported by the target client. Only the selected key is required, including
dry runs; discovery is anonymous. No OAuth, signup, server-issued key or
`Authorization` is used. Protect plaintext env files as described above and
do not source them as shell code.

Client snippet flags take environment **names**, never values. Keep every
selected header's source variable distinct, especially the independent client
secret; do not reuse a provider key as the secret. The stdout generator neither
reads files nor environment values and cannot prove value independence.
The HTTP server rejects a client secret equal to any supplied provider key
with HTTP 400 `CREDENTIAL_REUSE` before tool execution, including discovery,
dry runs and upload preparation. Generate an independent 32-random-byte
client secret as 64 lowercase hex and update only its protected client entry;
leave provider keys unchanged. For temporary uploads, the operator must enroll
the replacement secret's SHA-256 digest. Never reveal the raw secret.
Optional endpoint variables require selected provider `modelark`; their values
must be operator-verified exact bindings. Unknown endpoints require operator
verification/binding, not customer AK/SK entry into this server.

The selected provider key authorizes earlier tasks; the client secret and
operator HMAC scope per-pod admission only. There is no local task-ownership
ledger or saved create receipt to recover. Clients sharing a provider key share
whatever access the provider permits. Use separate provider credentials for
independent authorization.
Validate configuration syntax and discovery without printing secret values;
exact-client header handling remains unverified until tested there.
Default discovery returns `connection=null`. Optional live HTTP
`check_connection=true` checks ModelArk/client-secret presence and exact
image/video bindings only; missing headers become issues, malformed headers
can be rejected before diagnostics. `configuration_valid=true` is not
authentication, live lineage or entitlement proof. Never use a paid call to
validate credentials without separate approval.

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.
