import assert from "node:assert/strict";
import { test } from "node:test";
import { toolReferenceGroups } from "./navigation.mjs";

test("audio has its own tool section", () => {
  const names = ["seed_audio_generate"];
  const groups = toolReferenceGroups(names.map((name) => ({ name })));
  const entries = Object.fromEntries(
    groups.map((group) => [group.label, group.items.map((item) => item.label)]),
  );
  assert.deepEqual(entries.Audio, ["seed_audio_generate"]);
  assert.equal(entries.Understanding, undefined);
  assert.equal(entries["3D"], undefined);
  assert.equal(entries["VOD AI MediaKit"], undefined);
  assert.equal(entries["Asset library"], undefined);
  assert.equal(entries.Avatars, undefined);
  assert.equal(groups.flatMap((group) => group.items).length, names.length);
  assert.ok(groups.every((group) => group.collapsed));
});

test("tool routes and exact MCP names remain unchanged", () => {
  const groups = toolReferenceGroups([{ name: "seed_audio_generate" }]);
  assert.deepEqual(groups[0].items, [
    {
      label: "seed_audio_generate",
      slug: "tool-reference/seed-audio-generate",
    },
  ]);
});

test("empty catalogs do not create empty navigation groups", () => {
  assert.deepEqual(toolReferenceGroups([]), []);
});

test("uncategorized tools fail visibly instead of disappearing from navigation", () => {
  assert.throws(
    () => toolReferenceGroups([{ name: "new_capability" }]),
    /Uncategorized tool: new_capability/,
  );
});

test("retired capability names cannot reappear in navigation", () => {
  for (const name of [
    "omnihuman_create_task",
    "omnihuman_get_task",
    "omnihuman_cancel_task",
    "speech_to_text",
    "hyper3d_create_task",
    "hitem3d_create_task",
    "vod_get_task",
    "ark_asset_create",
    "seed_understand",
    "seed_audio_understand",
    "ark_job_submit",
    "ark_job_get",
    "ark_job_cancel",
    "ark_job_capabilities",
  ]) {
    assert.throws(
      () => toolReferenceGroups([{ name }]),
      new RegExp(`Uncategorized tool: ${name}`),
    );
  }
});

test("duplicate catalog entries cannot create duplicate navigation links", () => {
  assert.throws(
    () =>
      toolReferenceGroups([
        { name: "seed_audio_generate" },
        { name: "seed_audio_generate" },
      ]),
    /Duplicate tool: seed_audio_generate/,
  );
});
