// Plain-node self-check for clampScale + normalizeColumns (no test
// framework in this repo). Run: node tests/clamp_check.mjs
// Mirrors the cases previously covered by test_smoke.py's
// test_columns_defaults_to_auto_and_survives_round_trip and
// test_columns_clamped_to_one_to_four before the columns/scale
// handling moved from server.py to client.js.
import assert from "node:assert/strict";
import {
  FALLBACK_SYMBOL,
  SYMBOL_TABLE,
  allDayEndBadge,
  clampScale,
  colorBucket,
  colorToSymbol,
  normalizeColumns,
  readOptions,
  renderDay,
  styleShortLabel,
} from "../client.js";

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

// -- symbol dots -----------------------------------------------------------
// The whole point of the option is that two feeds never share a glyph, so
// the table has to cover every bucket colorBucket can return, with no
// repeats. A short table (18 symbols for 19 buckets) sent vivid pinks to
// the same bullet as black; a repeated glyph did the same to grey and pale
// red. Both are silent failures on the panel, so assert the invariant.
const { symbols, names } = SYMBOL_TABLE;
assert.equal(symbols.length, 19, "one symbol per bucket");
assert.equal(names.length, symbols.length, "every bucket is named");
assert.equal(new Set(symbols).size, symbols.length, "no two buckets share a symbol");

// Bucket layout: 0-2 greyscale by lightness, 3-10 low-saturation hues,
// 11-18 the same hues at high saturation.
assert.equal(colorBucket("#000000"), 0, "black is the darkest greyscale bucket");
assert.equal(colorBucket("#808080"), 1, "mid grey");
assert.equal(colorBucket("#FFFFFF"), 2, "white is the lightest greyscale bucket");
assert.equal(colorBucket("#FF0000"), 11, "vivid red is a high-saturation bucket");
assert.ok(colorBucket("#E91E63") <= 18, "vivid pink stays inside the table");
assert.notEqual(colorBucket("#E91E63"), colorBucket("#000000"), "vivid pink is not black");
assert.notEqual(colorToSymbol("#E91E63"), colorToSymbol("#000000"), "and does not share its glyph");
assert.notEqual(colorToSymbol("#808080"), colorToSymbol("#FF8080"), "grey and pale red differ");

// Known limit, worth pinning so a future change to the bucket maths shows
// up as a diff here: 8 even hue slices mean 0-45 degrees covers red through
// orange to yellow, so Google Calendar's Tomato, Tangerine and Banana all
// land on one glyph. Feeds whose colours sit close together need to be
// pulled apart by hand. Saturation still separates the pale variants.
const GCAL = {
  Tomato: "#D50000",
  Flamingo: "#E67C73",
  Tangerine: "#F4511E",
  Banana: "#F6BF26",
  Sage: "#33B679",
  Basil: "#0B8043",
  Peacock: "#039BE5",
  Blueberry: "#3F51B5",
  Lavender: "#7986CB",
  Grape: "#8E24AA",
  Graphite: "#616161",
};
const distinct = new Set(Object.values(GCAL).map(colorToSymbol));
assert.equal(distinct.size, 8, "the 11 stock Google colours resolve to 8 distinct glyphs");
assert.notEqual(colorToSymbol(GCAL.Flamingo), colorToSymbol(GCAL.Tomato), "saturation splits the reds");
assert.notEqual(colorToSymbol(GCAL.Lavender), colorToSymbol(GCAL.Blueberry), "saturation splits the blues");
assert.notEqual(colorToSymbol(GCAL.Graphite), colorToSymbol(GCAL.Basil), "greyscale is not a hue");
assert.equal(
  colorToSymbol(GCAL.Tomato),
  colorToSymbol(GCAL.Banana),
  "documented limit: red and yellow share the 0-45 degree slice"
);

// Every bucket is reachable and in range across the hue wheel.
for (let deg = 0; deg < 360; deg += 5) {
  for (const sat of [0.3, 1]) {
    const hex = hsvToHex(deg, sat, 1);
    const bucket = colorBucket(hex);
    assert.ok(
      Number.isInteger(bucket) && bucket >= 0 && bucket < symbols.length,
      `bucket for ${hex} (h=${deg} s=${sat}) is in range, got ${bucket}`
    );
    assert.ok(symbols.includes(colorToSymbol(hex)), `${hex} maps to a real symbol`);
  }
}

// calendar_core validates feed colours as #rrggbb, but a hand-edited feed
// store can carry anything. Anything else must fall back rather than
// parsing to NaN and rendering the string "undefined" into the rail.
for (const bad of ["#abc", "red", "", "#12345g", "rgb(1,2,3)", undefined, null, 42]) {
  assert.equal(colorToSymbol(bad), FALLBACK_SYMBOL, `unusable colour ${String(bad)} falls back`);
}

function hsvToHex(h, s, v) {
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  const seg = Math.floor(h / 60) % 6;
  const [r, g, b] = [
    [c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x],
  ][seg];
  const to8 = (n) => Math.round((n + m) * 255).toString(16).padStart(2, "0");
  return `#${to8(r)}${to8(g)}${to8(b)}`;
}

// allDayEndBadge: a multi-day all-day event is rendered on every day the
// server bucketed it into; the badge marks the copies that carry on past
// the day they sit under. It must NOT hide those copies (the bug where a
// holiday showed only on its first day and left the rest blank).
const holiday = { summary: "Holiday", end_date: "2026-08-20" };
assert.equal(allDayEndBadge(holiday, "2026-08-18"), "AUG 20", "first day badges the end");
assert.equal(allDayEndBadge(holiday, "2026-08-19"), "AUG 20", "middle day still badges the end");
assert.equal(allDayEndBadge(holiday, "2026-08-20"), "", "last day of the span has nothing left to point at");
assert.equal(allDayEndBadge(holiday, "2026-08-21"), "", "past the end (shouldn't happen) stays quiet");
assert.equal(
  allDayEndBadge({ summary: "Holiday", end_date: "2026-09-02" }, "2026-08-31"),
  "SEP 2",
  "crosses a month boundary"
);
assert.equal(allDayEndBadge({ summary: "Bin day" }, "2026-08-18"), "", "single-day event: no end_date, no badge");
assert.equal(allDayEndBadge({ end_date: "" }, "2026-08-18"), "", "blank end_date");
assert.equal(allDayEndBadge({ end_date: "junk" }, "2026-08-18"), "", "unparsable end_date");
assert.equal(allDayEndBadge({ end_date: "2026-08-20" }, ""), "", "missing day date");

// renderDay must paint an all-day bar on EVERY day the server bucketed
// the event into — never the "(no events)" placeholder. The placeholder
// showing up on a day that carries an all-day copy is the exact symptom
// the span-dedupe caused.
const middleDay = {
  date_iso: "2026-08-19", day_of_month: 19, day_of_week_short: "WED", month_short: "AUG",
  is_today: false,
  events: [{ summary: "Public Holiday", all_day: true, colour: "#36c", end_date: "2026-08-20" }],
};
const middleHtml = renderDay(middleDay, "24h", true, false, "short");
assert.match(middleHtml, /all-day-title">Public Holiday</, "middle day of a span still paints the bar");
assert.match(middleHtml, /all-day-span">&rarr; AUG 20</, "and badges where it ends");
assert.doesNotMatch(middleHtml, /day-empty/, "a day carrying an all-day event is never '(no events)'");

const lastDayHtml = renderDay({ ...middleDay, date_iso: "2026-08-20" }, "24h", true, false, "short");
assert.match(lastDayHtml, /all-day-title">Public Holiday</, "last day of a span paints the bar too");
assert.doesNotMatch(lastDayHtml, /all-day-span/, "no badge once the span ends here");

const emptyHtml = renderDay({ ...middleDay, events: [] }, "24h", true, false, "short");
assert.match(emptyHtml, /day-empty/, "a genuinely empty day still says so");

console.log("clamp_check.mjs: all assertions passed");
