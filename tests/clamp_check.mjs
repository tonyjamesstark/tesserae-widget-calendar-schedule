// Plain-node self-check for clampScale + normalizeColumns (no test
// framework in this repo). Run: node tests/clamp_check.mjs
// Mirrors the cases previously covered by test_smoke.py's
// test_columns_defaults_to_auto_and_survives_round_trip and
// test_columns_clamped_to_one_to_four before the columns/scale
// handling moved from server.py to client.js.
import assert from "node:assert/strict";
import { clampScale, normalizeColumns, readOptions, styleShortLabel } from "../client.js";

// normalizeColumns
assert.equal(normalizeColumns(undefined), "auto", "missing defaults to auto");
assert.equal(normalizeColumns(null), "auto", "null defaults to auto");
assert.equal(normalizeColumns("auto"), "auto");
assert.equal(normalizeColumns("AUTO"), "auto", "case-insensitive");
assert.equal(normalizeColumns("2"), 2);
assert.equal(normalizeColumns(4), 4);
assert.equal(normalizeColumns("9"), 4, "above max clamps down");
assert.equal(normalizeColumns("0"), 1, "below min clamps up");
assert.equal(normalizeColumns("lots"), 1, "unparsable falls back to 1");

// clampScale
assert.equal(clampScale(undefined, 1.0, 0.7, 1.5), 1.0, "missing falls back to default");
assert.equal(clampScale(9, 1.0, 0.7, 1.5), 1.5, "above max clamps down");
assert.equal(clampScale(0.01, 0.9, 0.6, 1.3), 0.6, "below min clamps up");
assert.equal(clampScale("not-a-number", 0.5, 0.0, 1.5), 0.5, "unparsable falls back to default");

// readOptions must pull from ctx.cell.options (the real ctx shape the
// composer sends) — not top-level ctx.options, which doesn't exist and
// would silently no-op every option this file reads from it (columns,
// date_label_style, all four scale sliders). show_location/time_format/
// etc. are server.py-side options, unaffected either way.
assert.deepEqual(
  readOptions({ cell: { options: { columns: "2" } } }),
  { columns: "2" },
  "reads from ctx.cell.options"
);
assert.deepEqual(readOptions({ options: { columns: "2" } }), {}, "ignores top-level ctx.options");
assert.deepEqual(readOptions({}), {}, "missing cell falls back to {}");

// date_label_style: short (server's as-sent label) / minimal (1-2 chars) / full.
const DOW_MINIMAL = { TUE: "TU", THU: "TH" };
const DOW_FULL = { TUE: "Tuesday" };
assert.equal(styleShortLabel("TUE", "short", DOW_MINIMAL), "TUE", "short passes the server label through unchanged");
assert.equal(styleShortLabel("TUE", "minimal", DOW_MINIMAL), "TU", "minimal uses the disambiguation map");
assert.equal(styleShortLabel("ZZZ", "minimal", {}), "ZZ", "unmapped label falls back to first 2 chars");
assert.equal(styleShortLabel("TUE", "full", DOW_MINIMAL, DOW_FULL), "Tuesday", "full looks up the whole word");
assert.equal(styleShortLabel("ZZZ", "full", {}, {}), "ZZZ", "unmapped full falls back to the short label as-is");

console.log("clamp_check.mjs: all assertions passed");
