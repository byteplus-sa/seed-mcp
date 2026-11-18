import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const python =
  process.env.ARK_DOCS_PYTHON ||
  join(
    root,
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python",
  );

test("stateless HTTP preserves direct execution without replay guarantees", () => {
  for (const path of [
    "specs/SPEC_DIRECT_EXECUTION.md",
    "specs/SPEC_HOSTED_BYOK.md",
    "docs/runtime.md",
    ".agents/skills/ark-mcp/SKILL.md",
    ".agents/skills/ark-mcp-setup/SKILL.md",
  ]) {
    const content = readFileSync(join(root, path), "utf8").replace(/\s+/g, " ");
    assert.match(content, /direct/i, path);
    assert.match(content, /stateless|database-free/i, path);
    assert.match(content, /per.pod/i, path);
    assert.match(content, /uncertain|reconciliation/i, path);
    assert.doesNotMatch(content, /HTTP.*requires.*fresh idempotency_key/, path);
  }
});

test("documented Python discovery runs on real stdio without credentials or spending", () => {
  const document = readFileSync(
    join(root, "docs/integrations/python.md"),
    "utf8",
  );
  const source = document.match(/```python\n([\s\S]*?)\n```/)[1];
  assert.match(source, /Client\(transport, timeout=660\)/);
  assert.match(source, /raise_on_error=False/);
  assert.doesNotMatch(source, /ark_job_|fastmcp_tasks|call_tool_task/);
  const uv = spawnSync(
    process.platform === "win32" ? "where" : "which",
    ["uv"],
    {
      encoding: "utf8",
    },
  );
  assert.equal(uv.status, 0, "The locked project environment requires uv");
  const temporary = mkdtempSync(join(tmpdir(), "seed-docs-direct-"));
  try {
    const launcher = [
      "import ast, json, sys",
      "data = json.load(sys.stdin)",
      "tree = ast.parse(data['source'])",
      "for statement in tree.body:",
      "    if isinstance(statement, ast.Assign):",
      "        for target in statement.targets:",
      "            if isinstance(target, ast.Name) and target.id in data['constants']:",
      "                statement.value = ast.Constant(data['constants'][target.id])",
      "ast.fix_missing_locations(tree)",
      "exec(compile(tree, '<documented-client>', 'exec'), {'__name__': '__main__'})",
    ].join("\n");
    const result = spawnSync(python, ["-I", "-B", "-c", launcher], {
      cwd: root,
      env: {
        PATH: process.env.PATH,
        HOME: temporary,
        ...(process.env.SystemRoot
          ? { SystemRoot: process.env.SystemRoot }
          : {}),
        ARTIFACT_DIR: join(temporary, "artifacts"),
        READINESS_CHECK_PROVIDERS: "false",
        UV_OFFLINE: "1",
      },
      input: JSON.stringify({
        source,
        constants: {
          UV: uv.stdout.trim().split(/\r?\n/)[0],
          CHECKOUT: root,
          ENV_FILE: join(temporary, "absent.env"),
        },
      }),
      encoding: "utf8",
      timeout: 30000,
    });
    assert.equal(result.status, 0, "Documented discovery must succeed offline");
    assert.match(result.stdout, /Connected; tool count: 4/);
    assert.match(result.stdout, /Models: \[\]/);
    assert.match(result.stdout, /Enabled services: \[\]/);
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});
