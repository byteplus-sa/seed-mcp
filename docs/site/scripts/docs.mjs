import { readFileSync } from "node:fs";
import { posix } from "node:path";
import examples from "../tool-examples.json" with { type: "json" };
import toolModels from "../tool-models.json" with { type: "json" };

export const SITE_BASE = "/ark-mcp";
export const SOURCE_BASE = "https://github.com/byteplus-sa/seed-mcp/blob/main/";
const understandingNotes = readFileSync(
  new URL("../tool-notes/understanding-retries.md", import.meta.url),
  "utf8",
);
const toolNotes = new Map([
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
  ["seed_understand", understandingNotes],
  ["seed_audio_understand", understandingNotes],
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
  const mode =
    tool.background === "required"
      ? "Background required"
      : tool.background === "optional"
        ? "Foreground or background"
        : "Foreground only";
  const input = tool.inputSchema;
  const inputRef = input.properties?.input?.$ref;
  const innerInput = inputRef
    ? input.$defs[inputRef.split("/").at(-1)]
    : input.properties?.input || input;
  const args = EXAMPLES[name];
  const asyncCreate = [
    "seedance_create_task",
    "omnihuman_create_task",
  ].includes(name);
  const httpArgs =
    args && asyncCreate && !args.input?.dry_run
      ? {
          ...args,
          input: {
            ...args.input,
            idempotency_key: "fa02c945-0497-4cd2-987b-e56b1de39915",
          },
        }
      : args;
  const call =
    args &&
    (tool.background === "required"
      ? {
          name: "ark_job_submit",
          arguments: { input: { tool_name: name, arguments: args } },
        }
      : { name, arguments: args });
  const execution =
    tool.background === "required"
      ? "On local stdio, submit through `ark_job_submit` with `tool_name` and the complete target `arguments`, including its inner `input` object. Poll `ark_job_get` using the returned Ark `job_id`, respecting `poll_after_ms`. Inspect both terminal status and `result.is_error`; the original output is in `result.structured_content`. Stdio rejects a direct foreground call."
      : tool.background === "optional"
        ? "On local stdio, use a direct foreground call for lightweight operations. Submit through `ark_job_submit` for explicit output persistence. The full arguments still include the `input` wrapper."
        : "Call this tool directly. It is not a background-job target.";
  const httpExecution = !http
    ? "**HTTP: unavailable.** This is a local stdio tool."
    : http.credential_header
      ? `**HTTP: direct foreground calls only.** Supply \`${http.credential_header}\` and \`X-MCP-Client-Secret\` privately in request headers, including dry runs. The client secret is client-generated 32 random bytes encoded as 64 lowercase hex. Only the selected provider key is needed. Keep persistence false; HTTP rejects true, local paths and stored artifact references. No jobs, native tasks, storage/artifact tools or resources exist on HTTP.`
      : "**HTTP: anonymous static discovery.** No provider key or client secret is required; it lists configured model bindings even without environment provider keys. `services[].enabled` reports registration, not entitlement. No provider calls are made.";
  const providerTasks = ["seedance_", "omnihuman_", "gen_task_"].some(
    (prefix) => name.startsWith(prefix),
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
| Local stdio execution | ${mode} |
| HTTP registration | ${http ? cell(http.registration_gate) : "Unavailable; local stdio only."} |
| HTTP execution | ${http ? "Direct foreground only; no native tasks." : "Unavailable."} |
| Catalog capability label | ${tool.scope ? `\`${tool.scope}\`` : "None"} |

This site lists all 21 local catalog entries. HTTP exposes 9 tools, or 12 with OmniHuman enabled, independently of operator provider keys. Use [model discovery](${SITE_BASE}/tool-reference/ark-list-models/) for your connection; [job discovery](${SITE_BASE}/tool-reference/ark-job-capabilities/) is stdio-only. Credentials never belong in tool arguments. HTTP has no OAuth, signup or server-issued key and never falls back to operator provider keys.

Catalog capability labels are metadata, not auth grants. See the [scope taxonomy](${SITE_BASE}/security/#scope-taxonomy).

${supportedModels(name)}

## Usage

Ask your connected AI client to use \`${name}\` for the operation you want.
The client constructs the arguments and handles tool calls. Review its proposed
operation before approving anything billable. For a non-billable introduction,
start with [discovery without generation](${SITE_BASE}/setup/first-run/#discover-before-spending).

${execution}

${httpExecution}

${asyncCreate ? `HTTP non-dry creates require \`idempotency_key\`: 16-128 ASCII letters, digits, underscores or hyphens. Generate a fresh UUID per intended create (one for the entire variation batch); replace the example UUID before first use. Repeat identical arguments and the same key only for delivery recovery, not polling. Only fully successful saved receipts replay, with ownership checked before upstream access, including Draft lookup. Running, failed, partial or cancelled attempts require reconciliation; never change keys to bypass uncertain acceptance. Keep known task/request IDs and poll existing tasks. Seedance dry runs need no key and use no journal; local stdio rejects a supplied key. See the [submission contract](${SOURCE_BASE}specs/SPEC_HOSTED_BYOK.md#http-submission-safety).` : ""}

${http ? "HTTP rejects explicit per-call `io.modelcontextprotocol/tasks` opt-in before provider dispatch, snapshot capture/save or queue creation, including discovery. Omit task opt-in; ordinary jobs are unavailable." : ""}

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

The following is a local stdio MCP tool-call envelope, not a shell command. Example media URLs and identifiers must be replaced with your own accessible resources. Seedream and Seedance examples are non-billable dry runs; other provider operations may incur charges.

\`\`\`json
${JSON.stringify(call, null, 2)}
\`\`\`

</details>
`
    : `Match the input fields below and the full JSON Schema. See the [worked examples](${SITE_BASE}/tools/) for this capability and [Background Execution](${SITE_BASE}/integration-guide/#background-execution) for job/result handling.`
}

${providerTasks ? `An Ark job ID is not a provider task ID. Seedance video tasks use [gen_task_get](${SITE_BASE}/tool-reference/gen-task-get/), and OmniHuman avatars use [omnihuman_get_task](${SITE_BASE}/tool-reference/omnihuman-get-task/). Foreground status checks default to \`persist_output=false\`; only stdio can explicitly persist through a background job. HTTP clients download expiring provider URLs themselves. Save accepted provider task IDs and resume polling instead of submitting a second generation.` : ""}

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

- Missing tool: check transport first; jobs/storage/artifacts are stdio-only. HTTP provider tools are credential-independent at registration; OmniHuman needs its enable flag. Local tools depend on [provider credentials](${SITE_BASE}/api-keys/).
- Invalid arguments: keep the correct wrapper and follow current model limits from discovery. A valid schema alone does not prove the chosen model supports the combination.
- A local job completes with an error: inspect the original tool result, not only the outer job status. Never automatically resubmit potentially billable work on either transport.
- Local output writes from jobs require server-configured \`OUTPUT_ROOTS\`; HTTP cannot write to a client's local disk.

See [configuration](${SITE_BASE}/configuration/), [background execution](${SITE_BASE}/integration-guide/#background-execution), and [artifact delivery](${SITE_BASE}/artifacts/).
`;
}
