import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_BACKGROUND, loadBackground } from "../src/background.ts";
import { translate } from "../src/i18n.ts";

test("background choice: galaxy at first; saved choice kept; bad values ignored", () => {
  assert.deepEqual(loadBackground(() => null), DEFAULT_BACKGROUND);
  assert.deepEqual(loadBackground(() => JSON.stringify({ mode: "matte", color: "#223344" })), { mode: "matte", color: "#223344", glass: 0.45 });
  assert.deepEqual(loadBackground(() => JSON.stringify({ mode: "clear", glass: 0.2 })).glass, 0.2);
  assert.equal(loadBackground(() => JSON.stringify({ mode: "clear", glass: 0.95 })).glass, 0.45);   // at most 90%
  assert.deepEqual(loadBackground(() => JSON.stringify({ mode: "clouds", color: "blue" })), DEFAULT_BACKGROUND);
  assert.deepEqual(loadBackground(() => "{bad"), DEFAULT_BACKGROUND);
  for (const k of ["bg.title", "bg.galaxy", "bg.aurora", "bg.matte", "bg.clear", "bg.glass"] as const) {
    assert.notEqual(translate("fa", k), k);
  }
});
