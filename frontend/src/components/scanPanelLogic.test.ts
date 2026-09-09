import assert from "node:assert/strict";
import test from "node:test";

import { getScanViewAction } from "./scanPanelLogic.ts";

test("clicking today's candidates starts the default scan when no result exists", () => {
  assert.equal(getScanViewAction("quick", false, false), "run-default");
});

test("clicking today's candidates does not duplicate an active or completed scan", () => {
  assert.equal(getScanViewAction("quick", true, false), "show-view");
  assert.equal(getScanViewAction("quick", false, true), "show-view");
});

test("other scan views only switch the visible view", () => {
  assert.equal(getScanViewAction("timing", false, false), "show-view");
});
