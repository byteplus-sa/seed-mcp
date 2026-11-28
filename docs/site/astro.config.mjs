import { readFileSync } from "node:fs";
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import mermaid from "astro-mermaid";
import { unified } from "@astrojs/markdown-remark";
import starlightLinksValidator from "starlight-links-validator";
import remarkLinks from "./scripts/remark-links.mjs";
import { toolReferenceGroups } from "./scripts/navigation.mjs";
import rehypeTables from "./scripts/rehype-tables.mjs";
import {
  REPOSITORY_URL,
  SITE_BASE,
  SITE_DESCRIPTION,
  SITE_ORIGIN,
  SITE_TITLE,
} from "./site-config.mjs";

const { tools } = JSON.parse(
  readFileSync(new URL("./src/data/tools.json", import.meta.url), "utf8"),
);

export default defineConfig({
  site: SITE_ORIGIN,
  base: SITE_BASE,
  trailingSlash: "always",
  outDir: "../../out/docs-site",
  redirects: {
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
            { slug: "setup/install", label: "Connect to Hosted Seed MCP" },
            { slug: "setup/agent-skill", label: "Agent Skill (Optional)" },
            { slug: "setup/shared-server", label: "HTTP Connection Details" },
            { slug: "api-keys", label: "Provider Keys" },
            { slug: "setup/first-run", label: "Your First Tool Call" },
          ],
        },
        {
          label: "Client Integrations",
          items: [
            { slug: "integrations", label: "Choose Your Client" },
            ...[
              "claude-desktop",
              "claude-code",
              "codex",
              "trae",
              "cursor",
              "vscode",
              "opencode",
              "python",
            ].map((client) => ({ slug: `integrations/${client}` })),
            { slug: "transports", label: "HTTP and Shared Servers" },
          ],
        },
        {
          label: "Tool Reference",
          collapsed: true,
          items: [
            { slug: "capabilities", label: "Choose a Tool" },
            ...toolReferenceGroups(tools),
          ],
        },
        {
          label: "Workflows and Concepts",
          collapsed: true,
          items: [
            { slug: "models" },
            { slug: "tools", label: "Worked Tool Examples" },
            { slug: "seed-tts", label: "Text to Speech (Local)" },
            { slug: "artifacts" },
            { slug: "multi-generation" },
            { slug: "assets" },
            { slug: "use-cases" },
            { slug: "integration-guide", label: "Direct Execution" },
          ],
        },
        {
          label: "Configuration and Operations",
          collapsed: true,
          items: [
            "configuration",
            "setup/manual-install",
            "setup/updating",
            "self-hosting",
            "deployment",
            "byteplus-terraform",
            "secret-manager",
            "runtime",
            "security",
            "observability",
            "s3-object-storage",
            "architecture",
            "api-reference",
            "releases",
            "changelog",
            "migration-02",
            "site-maintenance",
          ].map((slug) => ({ slug })),
        },
        { slug: "troubleshooting" },
      ],
    }),
  ],
});
