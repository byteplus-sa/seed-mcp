import { readFileSync } from "node:fs";
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import mermaid from "astro-mermaid";
import { unified } from "@astrojs/markdown-remark";
import starlightLinksValidator from "starlight-links-validator";
import remarkLinks from "./scripts/remark-links.mjs";
import { toolReferenceGroups } from "./scripts/navigation.mjs";
import rehypeTables from "./scripts/rehype-tables.mjs";
import { selectHostedTools } from "./scripts/publication.mjs";
import {
  REPOSITORY_URL,
  SITE_BASE,
  SITE_DESCRIPTION,
  SITE_ORIGIN,
  SITE_TITLE,
} from "./site-config.mjs";

const { tools, redirects } = JSON.parse(
  readFileSync(new URL("./src/data/tools.json", import.meta.url), "utf8"),
);

export default defineConfig({
  site: SITE_ORIGIN,
  base: SITE_BASE,
  trailingSlash: "always",
  outDir: "../../out/docs-site",
  redirects: {
    ...redirects,
    "/seedream-5-5/": `${SITE_BASE}/tool-reference/seedream-generate-image/#seedream-5-5`,
  },
  markdown: {
    processor: unified({
      remarkPlugins: [remarkLinks],
      rehypePlugins: [rehypeTables],
    }),
  },
  integrations: [
    mermaid({
      autoTheme: true,
      enableLog: false,
      mermaidConfig: {
        securityLevel: "strict",
      },
    }),
    starlight({
      title: SITE_TITLE,
      logo: {
        light: "./src/assets/byteplus-mark-light.svg",
        dark: "./src/assets/byteplus-mark-dark.svg",
        alt: "",
      },
      description: SITE_DESCRIPTION,
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: REPOSITORY_URL,
        },
      ],
      editLink: {
        baseUrl: `${REPOSITORY_URL}/edit/main/docs/`,
      },
      customCss: ["./src/styles/custom.css"],
      plugins: [starlightLinksValidator({ errorOnRelativeLinks: false })],
      expressiveCode: {
        themes: ["vitesse-black", "vitesse-light"],
        styleOverrides: {
          borderRadius: "8px",
          borderColor: "var(--sl-color-hairline)",
          codeBackground: "var(--sl-color-gray-6)",
        },
      },
      sidebar: [
        {
          label: "Get Started",
          items: [
            { slug: "setup/install", label: "Connect" },
            { slug: "setup/first-run", label: "Create Media" },
            { slug: "capabilities", label: "Tools at a Glance" },
            { slug: "files", label: "Reference Files" },
          ],
        },
        {
          label: "Tool Reference",
          collapsed: true,
          items: toolReferenceGroups(selectHostedTools(tools)),
        },
        {
          label: "Help",
          items: [
            { slug: "api-keys", label: "Get API Keys" },
            { slug: "help", label: "Troubleshooting" },
            { slug: "service", label: "Service Limits and Privacy" },
          ],
        },
        {
          label: "Advanced",
          collapsed: true,
          items: [
            { slug: "connection-checks", label: "Connection Checks" },
            { slug: "calling-tools", label: "Calling Tools" },
            { slug: "agent-skill", label: "Agent Skill (Optional)" },
            {
              label: "Operator and Local Reference",
              link: `${REPOSITORY_URL}/tree/main/docs`,
            },
          ],
        },
      ],
    }),
  ],
});
