---
title: Agent Skill (Optional)
description: Add media workflow instructions to a supported coding agent.
---

The `ark-mcp` skill helps an agent discover models, create media, poll video
tasks and keep results. **It is optional and does not install or run the
server.** [Connect to hosted Seed MCP](setup/install.md) first.

## Install

With Node.js 22.20+, npm/npx and Git already available, run:

```bash
npx skills add byteplus-sa/seed-mcp --skill ark-mcp -g
```

Select only your agent. `-g` installs user-wide; omit it for project scope.
Review the instructions before use and ask before replacing an existing skill.
Use the Seed MCP fork, not the broader upstream Ark MCP bundle.
Other MCP clients may not support skills.

The Skills CLI uses installation telemetry by default.
See its [privacy and opt-out options](https://skills.sh/docs/faq).

## Verify

Refresh the agent's skill list and ask:

```text
Load the ark-mcp skill and explain how you will discover models, create media,
check existing tasks and save results. Do not generate or upload anything.
```

This checks instruction loading, not provider access.
The connected server's tool schemas remain authoritative.

For manual installation, supported paths and scoped updates, see the
[repository skill guide](https://github.com/byteplus-sa/seed-mcp/blob/main/docs/setup/agent-skill.md).
