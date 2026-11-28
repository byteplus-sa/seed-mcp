import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { HOSTED_TOOLS, PUBLIC_PAGES, sourceRoute } from "./publication.mjs";
import { SITE_BASE, SITE_ORIGIN } from "../site-config.mjs";

const output = new URL("../../../out/docs-site/", import.meta.url);

function htmlFiles(directory = output, prefix = "") {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = `${prefix}${entry.name}`;
    if (entry.isDirectory()) {
      return htmlFiles(new URL(`${entry.name}/`, directory), `${path}/`);
    }
    return entry.isFile() && path.endsWith(".html") ? [path] : [];
  });
}

const routes = [
  ...PUBLIC_PAGES.filter((source) => source !== "404.md").map(sourceRoute),
  ...HOSTED_TOOLS.map(
    (name) => `/tool-reference/${name.replaceAll("_", "-")}/`,
  ),
];
const expected = routes.map((route) => `${route.slice(1)}index.html`).sort();
const searchable = [];
let redirects = 0;
for (const path of htmlFiles()) {
  const html = readFileSync(new URL(path, output), "utf8");
  if (html.includes("data-pagefind-body")) {
    searchable.push(path);
  } else if (path !== "404.html") {
    assert.match(html, /name="robots" content="noindex"/, path);
    assert.match(html, /http-equiv="refresh"/, path);
    redirects += 1;
  }
}
assert.deepEqual(
  searchable.sort(),
  expected,
  "Only curated pages belong in site search",
);

const sitemap = readFileSync(new URL("sitemap-0.xml", output), "utf8");
const urls = [...sitemap.matchAll(/<loc>(.*?)<\/loc>/g)]
  .map((match) => match[1])
  .sort();
assert.deepEqual(
  urls,
  routes.map((route) => `${SITE_ORIGIN}${SITE_BASE}${route}`).sort(),
  "Redirects and repository-only pages must stay out of the sitemap",
);
assert.doesNotMatch(
  readFileSync(new URL("404.html", output), "utf8"),
  /This content is a draft/,
);
console.log(
  `Verified ${searchable.length} searchable pages, one 404 page and ${redirects} legacy redirects.`,
);
