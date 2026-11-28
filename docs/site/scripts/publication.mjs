import { readdirSync } from "node:fs";
import { REPOSITORY_URL, SITE_BASE } from "../site-config.mjs";

export const SOURCE_BASE = `${REPOSITORY_URL}/blob/main/`;
export const PUBLIC_PAGES = [
  "index.mdx",
  "setup/install.md",
  "setup/first-run.md",
  "api-keys.md",
  "capabilities.md",
  "connection-checks.md",
  "agent-skill.md",
  "calling-tools.md",
  "help.md",
  "service.md",
  "404.md",
];
export const HOSTED_TOOLS = [
  "ark_list_models",
  "seedream_generate_image",
  "seedance_create_task",
  "gen_task_get",
  "gen_task_list",
  "gen_task_cancel_or_delete",
  "seed_audio_generate",
];

const consolidated = {
  "setup/shared-server.md": "connection-checks/",
  "setup/agent-skill.md": "agent-skill/",
  "integration-guide.md": "calling-tools/",
  "troubleshooting.md": "help/",
  "getting-started.md": "setup/install/",
  "integrations/index.md": "setup/install/#clients",
  "integrations/codex.md": "setup/install/#codex",
  "integrations/claude-code.md": "setup/install/#claude-code",
  "integrations/claude-desktop.md": "setup/install/#other-clients",
  "integrations/trae.md": "setup/install/#trae",
  "integrations/cursor.md": "setup/install/#other-clients",
  "integrations/vscode.md": "setup/install/#other-clients",
  "integrations/opencode.md": "setup/install/#opencode",
};

export function collectSources(
  directory = new URL("../../", import.meta.url),
  prefix = "",
) {
  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      if (entry.name === "site") return [];
      const source = `${prefix}${entry.name}`;
      if (entry.isDirectory()) {
        return collectSources(
          new URL(`${entry.name}/`, directory),
          `${source}/`,
        );
      }
      return entry.isFile() && /\.mdx?$/.test(source) ? [source] : [];
    })
    .sort();
}

export function sourceRoute(source) {
  const slug = source
    .replace(/\.mdx?$/, "")
    .replaceAll(".", "")
    .replace(/(?:^|\/)index$/, "");
  return `/${slug ? `${slug}/` : ""}`;
}

export function documentTarget(source) {
  if (PUBLIC_PAGES.includes(source))
    return `${SITE_BASE}${sourceRoute(source)}`;
  if (consolidated[source]) return `${SITE_BASE}/${consolidated[source]}`;
  return `${SOURCE_BASE}docs/${source}`;
}

export function appendSuffix(target, suffix) {
  const [path, destinationFragment] = target.split("#");
  const [query, sourceFragment] = suffix.split("#");
  const fragment = destinationFragment ?? sourceFragment;
  return `${path}${query}${fragment === undefined ? "" : `#${fragment}`}`;
}

const sourcesByRoute = new Map(
  collectSources().map((source) => [sourceRoute(source), source]),
);

export function resolveSiteLink(target) {
  if (!target.startsWith(`${SITE_BASE}/`)) return target;
  const [, path, suffix] = target.match(/^([^?#]*)(.*)$/);
  const source = sourcesByRoute.get(path.slice(SITE_BASE.length));
  return source ? appendSuffix(documentTarget(source), suffix) : target;
}

export function selectHostedTools(tools) {
  const names = new Set();
  for (const tool of tools) {
    if (names.has(tool.name)) throw new Error(`Duplicate tool: ${tool.name}`);
    names.add(tool.name);
  }
  return HOSTED_TOOLS.map((name) => {
    const tool = tools.find((entry) => entry.name === name);
    if (!tool?.transports?.http || tool.execution !== "direct") {
      throw new Error(`Missing direct HTTP contract: ${name}`);
    }
    return tool;
  });
}

export function siteRedirects(sources, tools) {
  const redirects = Object.fromEntries(
    sources
      .filter((source) => !PUBLIC_PAGES.includes(source))
      .map((source) => [sourceRoute(source), documentTarget(source)]),
  );
  for (const tool of tools) {
    if (HOSTED_TOOLS.includes(tool.name)) continue;
    redirects[`/tool-reference/${tool.name.replaceAll("_", "-")}/`] =
      `${SOURCE_BASE}src/ark_mcp/tools/${tool.name}.py`;
  }
  return redirects;
}
