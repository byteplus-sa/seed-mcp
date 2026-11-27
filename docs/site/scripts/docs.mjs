import { readFileSync } from "node:fs";
import { posix } from "node:path";
import examples from "../tool-examples.json" with { type: "json" };
import toolModels from "../tool-models.json" with { type: "json" };

export const SITE_BASE = "/ark-mcp";
export const SOURCE_BASE = "https://github.com/byteplus-sa/seed-mcp/blob/main/";
const toolNotes = new Map([
  [
    "ark_list_models",
    readFileSync(
      new URL("../tool-notes/ark-list-models.md", import.meta.url),
      "utf8",
    ),
  ],
  [
    "seedream_generate_image",
    readFileSync(
      new URL("../tool-notes/seedream-generate-image.md", import.meta.url),
      "utf8",
    ),
  ],
  [
    "seedance_create_task",
    readFileSync(
      new URL("../tool-notes/seedance-create-task.md", import.meta.url),
      "utf8",
    ),
  ],
]);

export function handbookPage(source, content, toolCount) {
  content = content.replaceAll("\r\n", "\n");
  const editUrl = JSON.stringify(
    `${SOURCE_BASE.replace("/blob/", "/edit/")}docs/${source.replaceAll("\\", "/")}`,
  );
  content = content.replaceAll("__TOOL_COUNT__", String(toolCount));
  if (content.startsWith("---\n")) {
    return content.replace(/^---\n([\s\S]*?)\n---/, (block, metadata) =>
      /^editUrl:/m.test(metadata)
        ? block
        : `---\n${metadata}\neditUrl: ${editUrl}\n---`,
    );
  }
  const title =
    content.match(/^# (.+)\r?$/m)?.[1] || source.replace(/\.mdx?$/, "");
  return `---\ntitle: ${JSON.stringify(title)}\neditUrl: ${editUrl}\n---\n\n${content.replace(/^# .+\r?\n/, "")}`;
}

export function resolveDocLink(source, target) {
  if (/^(?:[a-z][a-z\d+.-]*:|#|\/)/i.test(target)) return target;
  const match = target.match(/^([^?#]*)(.*)$/);
  const path = posix.normalize(
    posix.join("docs", posix.dirname(source), decodeURI(match[1])),
  );
  if (path.startsWith("../"))
    throw new Error(`Link outside repository: ${source}: ${target}`);
  if (path.startsWith("docs/") && /\.mdx?$/.test(path)) {
    const slug = path
      .slice(5)
      .replace(/\.mdx?$/, "")
      .replaceAll(".", "")
      .replace(/(?:^|\/)index$/, "");
    return `${SITE_BASE}/${slug ? `${slug}/` : ""}${match[2]}`;
  }
  return `${SOURCE_BASE}${path}${match[2]}`;
}

function cell(value) {
  return String(value).replaceAll("|", "\\|").replace(/\r?\n/g, " ");
}

function fieldType(field) {
  if (field.$ref) return field.$ref.split("/").at(-1);
  if (field.anyOf || field.oneOf)
    return (field.anyOf || field.oneOf).map(fieldType).join(" or ");
  if (field.enum)
    return field.enum.map((value) => JSON.stringify(value)).join(", ");
  if ("const" in field) return JSON.stringify(field.const);
  if (field.type === "array") return `array of ${fieldType(field.items || {})}`;
  return field.type || "object";
}

export function schemaTable(schema) {
  const fields = Object.entries(schema.properties || {});
  if (fields.length === 0) return "No fields. Pass `{}`.\n";
  const rows = [
    "| Field | Type | Required | Description and constraints |",
    "| --- | --- | --- | --- |",
  ];
  for (const [name, field] of fields) {
    const constraints = [
      "minimum",
      "maximum",
      "exclusiveMinimum",
      "exclusiveMaximum",
      "minLength",
      "maxLength",
      "minItems",
      "maxItems",
      "pattern",
      "format",
    ].flatMap((key) =>
      [field, ...(field.anyOf || field.oneOf || [])]
        .filter((branch) => key in branch)
        .map(
          (branch) =>
            `${branch === field ? "" : `${fieldType(branch)}: `}${key}: ${JSON.stringify(branch[key])}`,
        ),
    );
    if ("default" in field)
      constraints.push(`Default: ${JSON.stringify(field.default)}`);
    const description = [field.description || "", ...constraints]
      .filter(Boolean)
      .join("; ");
    rows.push(
      `| \`${cell(name)}\` | ${cell(fieldType(field))} | ${(schema.required || []).includes(name) ? "Yes" : "No"} | ${cell(description)} |`,
    );
  }
  return `${rows.join("\n")}\n`;
}

export const EXAMPLES = examples;

function supportedModels(name) {
  const entry = toolModels[name];
  if (!entry) return "";
  const rows = entry.models.map(
    (model) =>
      `| ${cell(model.name)} | ${cell(model.id)} | ${cell(model.availability)} | ${cell(model.capabilities)} |`,
  );
  const anchor =
    name === "seedream_generate_image"
      ? '<span id="seedream-5-5"></span>\n<span id="seedream-55"></span>\n\n'
      : "";
  return `${anchor}## Supported Models

These are supported families and built-in model or service IDs for this site revision, not provider account access or a guarantee that every row is enabled on your server. Check [model discovery](${SITE_BASE}/tool-reference/ark-list-models/) for configured bindings and service availability.

| Model | Model or service ID | Availability | Capabilities |
| --- | --- | --- | --- |
${rows.join("\n")}

${entry.selection}
`;
}

export function toolPage(tool) {
  const name = tool.name;
  const http = tool.transports?.http;
  const stdio = tool.transports?.stdio;
  const upload = name === "media_prepare_upload";
  if (
    tool.execution !== "direct" ||
    "background" in tool ||
    Object.values(tool.transports || {}).some(
      (transport) =>
        transport &&
        (transport.execution !== "direct" || "background" in transport),
    )
  ) {
    throw new Error(`Invalid direct execution metadata: ${name}`);
  }
  const input = tool.inputSchema;
  const inputRef = input.properties?.input?.$ref;
  const innerInput = inputRef
    ? input.$defs[inputRef.split("/").at(-1)]
    : input.properties?.input || input;
  const args = EXAMPLES[name];
  const asyncCreate = ["seedance_create_task"].includes(name);
  const httpArgs = args;
  const call = args && { name, arguments: args };
  const execution =
    "Call this tool directly on either supported transport, keeping its `input` wrapper. Inspect `is_error` before using `structured_content`. No MCP jobs, worker queue or native tasks exist. Local stdio supports explicit persistence; HTTP remains URL-only.";
  const httpExecution = !http
    ? "**HTTP: unavailable.** This is a local stdio tool."
    : upload
      ? "**HTTP: opt-in upload preparation.** Supply only operator-enrolled `X-MCP-Client-Secret` privately. No generation-provider key is needed for preparation. The upload-capable client sends binary data directly to TOS using every signed field unchanged and the file field LAST. Wait for upload success before using `reference_url`. This tool does not upload, inspect bytes or verify the object. See [temporary uploads](/ark-mcp/temporary-uploads/)."
      : http.credential_header
        ? `**HTTP: direct foreground calls only.** Supply \`${http.credential_header}\` and \`X-MCP-Client-Secret\` privately in request headers, including dry runs. The client secret is client-generated 32 random bytes encoded as 64 lowercase hex. Only the selected provider key is needed. Keep persistence false; HTTP rejects true, local paths and stored artifact references. No jobs, native tasks, local storage/artifact tools or resources exist on HTTP. Optional temporary upload preparation is separate.`
        : "**HTTP: anonymous static discovery.** No provider key or client secret is required; it lists configured model bindings even without environment provider keys. `services[].enabled` reports registration, not entitlement. No provider calls are made.";
  const providerTasks = ["seedance_", "gen_task_"].some((prefix) =>
    name.startsWith(prefix),
  );
  return `---
title: ${JSON.stringify(name)}
description: ${JSON.stringify(`Inputs, outputs, setup requirements and execution guidance for ${name}.`)}
editUrl: ${JSON.stringify(`${SOURCE_BASE.replace("/blob/", "/edit/")}${tool.module?.replaceAll(".", "/").replace(/^ark_mcp/, "src/ark_mcp") || `src/ark_mcp/tools/${name}`}.py`)}
---

${tool.description}

## Setup

| Requirement | Value |
| --- | --- |
| Local stdio registration | ${cell(tool.registration_gate)} |
| Local stdio execution | ${stdio ? "Direct" : "Unavailable."} |
| HTTP registration | ${http ? cell(http.registration_gate) : "Unavailable; local stdio only."} |
| HTTP execution | ${http ? "Direct foreground only; no native tasks." : "Unavailable."} |
| Catalog capability label | ${tool.scope ? `\`${tool.scope}\`` : "None"} |

This site lists 14 catalog entries: 13 conditional local tools (four always registered) plus HTTP-only upload preparation. HTTP exposes 7 tools, plus one when temporary uploads are enabled. HTTP generation registration is independent of operator provider keys; Seed TTS is stdio only. Use [model discovery](${SITE_BASE}/tool-reference/ark-list-models/) and tools/list for your connection. Credentials never belong in tool arguments. HTTP has no OAuth, signup or server-issued key and never falls back to operator generation-provider keys.

Catalog capability labels are metadata, not auth grants. See the [scope taxonomy](${SITE_BASE}/security/#scope-taxonomy).

${supportedModels(name)}

## Usage

Ask your connected AI client to use \`${name}\` for the operation you want.
The client constructs the arguments and handles tool calls. Review its proposed
operation before approving anything billable. For a non-billable introduction,
start with [discovery without generation](${SITE_BASE}/setup/first-run/#discover-before-spending).

${execution}

${httpExecution}

${asyncCreate ? `HTTP is stateless: omit \`idempotency_key\`; legacy keys are rejected. There is no database, saved-response replay or deduplication. Repeating a create may generate and bill again. Retain task/request IDs, poll existing tasks, and reconcile uncertain acceptance through the provider instead of automatically resubmitting. Task access is authorized by the supplied provider key, not the client secret. See the [submission contract](${SOURCE_BASE}specs/SPEC_HOSTED_BYOK.md#http-submission-safety).` : ""}

Both transports reject explicit per-call \`io.modelcontextprotocol/tasks\` opt-in, including discovery, before provider dispatch. Omit task opt-in.

Use a 660-second client timeout with the default 600-second cooperative tool deadline (\`MCP_TOOL_TIMEOUT_SECONDS\`, positive finite, maximum 3600). Owner-first provider admission waits at most 2 seconds by default (\`MCP_ADMISSION_TIMEOUT_SECONDS\`, positive finite, maximum 30). SQLite/SDK cleanup may exceed the nominal deadline. \`ADMISSION_TIMEOUT\` means this attempt did not dispatch, not that other variations did not. \`TOOL_DEADLINE_EXCEEDED\` can retain known accepted IDs and uncertainty; never blindly resubmit.

${
  http && args
    ? `### HTTP Call

The same input schema is used directly, without a job wrapper. Configure private headers separately; examples contain no credentials.

\`\`\`json
${JSON.stringify({ name, arguments: httpArgs }, null, 2)}
\`\`\`
`
    : ""
}

${
  call
    ? `<details>
<summary>Exact MCP call (for developers)</summary>

The following is ${stdio ? "a local stdio" : "an HTTP-only"} MCP tool-call envelope, not a shell command. Example media URLs and identifiers must be replaced with your own accessible resources. Seedream and Seedance examples are non-billable dry runs; other provider operations may incur charges.

\`\`\`json
${JSON.stringify(call, null, 2)}
\`\`\`

</details>
`
    : `Match the input fields below and the full JSON Schema. See the [worked examples](${SITE_BASE}/tools/) and [Direct Execution](${SITE_BASE}/integration-guide/#direct-execution) for result handling.`
}

${providerTasks ? `Seedance video tasks use [gen_task_get](${SITE_BASE}/tool-reference/gen-task-get/). These are provider-managed queues, not MCP jobs. Status checks default to \`persist_output=false\`; only stdio can explicitly persist in a direct call. HTTP clients download expiring provider URLs themselves. Save accepted provider task IDs and resume polling instead of submitting a second generation.` : ""}

${toolNotes.get(name) || ""}

## Inputs

${input.properties?.input ? 'The MCP arguments object wraps these fields as `{"input": {...}}`.' : "This tool has no `input` wrapper."}

${schemaTable(innerInput)}

## Outputs

${schemaTable(tool.outputSchema)}

## Nested Types

Field types named above refer to these shared definitions. Optional/null fields, enum choices and bounds are retained in the complete schemas below. Schema validation is followed by runtime capability and security checks.

${Object.entries(input.$defs || {})
  .map(
    ([name, schema]) =>
      `<details>\n<summary>${name}</summary>\n\n${schemaTable(schema)}\n</details>\n`,
  )
  .join("\n")}

## Complete JSON Schemas

<details>
<summary>Input schema, including the MCP wrapper</summary>

\`\`\`json
${JSON.stringify(input, null, 2)}
\`\`\`

</details>

<details>
<summary>Output schema, including nested definitions</summary>

\`\`\`json
${JSON.stringify(tool.outputSchema, null, 2)}
\`\`\`

</details>

## Troubleshooting

- Missing tool: check transport first; local storage/artifacts are stdio-only. Temporary upload preparation needs its operator enable flag and enrollment. HTTP generation-provider tools are credential-independent at registration. Local tools depend on [provider credentials](${SITE_BASE}/api-keys/).
- Invalid arguments: keep the correct wrapper and follow current model limits from discovery. A valid schema alone does not prove the chosen model supports the combination.
- A direct call returns an error: inspect safe task/request IDs, including partial acceptance. Never automatically resubmit potentially billable work on either transport.
- Local output writes require live MCP roots or server-configured \`OUTPUT_ROOTS\`; HTTP cannot write to a client's local disk.

See [configuration](${SITE_BASE}/configuration/), [direct execution](${SITE_BASE}/integration-guide/#direct-execution), and [artifact delivery](${SITE_BASE}/artifacts/).
`;
}
