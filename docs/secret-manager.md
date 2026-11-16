# Secret Handling for BYOK

Hosted provider-secret sync is superseded. HTTP receives customer provider
keys only in live request headers; the server does not store a provider-key
bundle and must not fetch one from Secret Manager.

See the [BYOK contract](../specs/SPEC_HOSTED_BYOK.md) and the
[superseded sync specification](../specs/SPEC_PROVIDER_SECRET_SYNC.md).
No old-auth or retained-state migration is supplied.

## Operator Secret

Store `MCP_IDENTITY_HMAC_KEY` through your approved secret-management process.
Generate 32 random bytes, represented as 64 lowercase hex characters, and keep
the value stable across restarts with `MCP_IDENTITY_KEY_VERSION` (default `1`).
It is operator identity configuration, not a customer credential.
Never distribute it to clients or include it in Terraform, logs, screenshots
or source control.

Only minimal state and identity configuration belong on the hosted server.
Do not add customer provider keys, client secrets, storage credentials or
Redis task-snapshot secrets to hosted configuration. The HTTP foundation
does not implement automatic secret rotation or a secret-management portal.

## Client Secrets

Clients use private provider-header configuration plus a client-generated
`X-MCP-Client-Secret`. The secret is 32 random bytes encoded as 64 lowercase
hex; keep it stable to retain access to the same owner scope.
Follow [private HTTP setup](setup/shared-server.md).

Use an OS secret store or a private file/injector supported by the client.
Keep credentials outside Git and chat. The server/operator sees the live
request, so use only a trusted HTTPS endpoint. Changing credentials changes
scope; there is no identity recovery bridge.

## Local stdio

Local tools still load provider keys from a private env file referenced by
`ARK_MCP_ENV_FILE`. The [API keys guide](api-keys.md) covers field names.
This is local startup configuration, not hosted provider-key synchronization.
