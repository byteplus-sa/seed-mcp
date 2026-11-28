import { spawnSync } from "node:child_process";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { handbookPage, hostedToolPage } from "./docs.mjs";
import {
  collectSources,
  PUBLIC_PAGES,
  selectHostedTools,
  siteRedirects,
} from "./publication.mjs";

const site = fileURLToPath(new URL("../", import.meta.url));
const repository = fileURLToPath(new URL("../../../", import.meta.url));
const docs = join(repository, "docs");
const generated = join(site, "src/content/docs");
const python =
  process.env.ARK_DOCS_PYTHON ||
  join(
    repository,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
const exported = spawnSync(
  python,
  ["-I", "-B", join(repository, "scripts/export_tool_docs.py")],
  {
    cwd: site,
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  },
);
if (exported.error || exported.status !== 0) {
  throw new Error(
    `Tool schema export failed. Run uv sync --locked first.\n${exported.error?.message || exported.stderr}`,
  );
}
const data = JSON.parse(exported.stdout);
if (!Array.isArray(data.tools) || !data.tools.length)
  throw new Error("Empty tool catalog.");

const sources = collectSources();
for (const source of PUBLIC_PAGES) {
  if (!sources.includes(source))
    throw new Error(`Missing public page: ${source}`);
}
const hostedTools = selectHostedTools(data.tools);

await rm(generated, { recursive: true, force: true });
await mkdir(generated, { recursive: true });
for (const filename of PUBLIC_PAGES) {
  const content = handbookPage(
    filename,
    await readFile(join(docs, filename), "utf8"),
    data.tools.length,
  );
  const destination = join(generated, filename);
  await mkdir(dirname(destination), { recursive: true });
  await writeFile(destination, content);
}
for (const tool of hostedTools) {
  const destination = join(
    generated,
    "tool-reference",
    `${tool.name.replaceAll("_", "-")}.md`,
  );
  await mkdir(dirname(destination), { recursive: true });
  await writeFile(destination, hostedToolPage(tool));
}
await mkdir(join(site, "src/data"), { recursive: true });
await writeFile(
  join(site, "src/data/tools.json"),
  JSON.stringify(
    { ...data, redirects: siteRedirects(sources, data.tools) },
    null,
    2,
  ) + "\n",
);
console.log(
  `Prepared ${PUBLIC_PAGES.length} guide pages and ${hostedTools.length} hosted tool pages; full ${data.tools.length}-tool catalog retained. No provider calls.`,
);
