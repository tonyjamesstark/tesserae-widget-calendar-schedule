# Calendar, Schedule

A [Tesserae](https://github.com/dmellok/tesserae) widget that paints a timeline-rail agenda view: upcoming events grouped by day, with a thin ink rail connecting per-event nodes and a coloured start-time chip carrying the feed accent. Titles wrap freely so the widget stays legible from 1 up to 4 narrow columns on wide e-ink panels.

Reads from the same `calendar_core` feeds the other calendar_* widgets use. Drop in alongside `calendar_day` / `calendar_week` / `calendar_month`; pick which feeds to include per cell.

## Screenshots

Same widget in the same cell (1200 × 800), different values of `days_ahead` with `columns` on **Auto**. The layout grows only as far as it needs to.

| Auto, 2 days (1 col) | Auto, 5 days (2 col) |
|---|---|
| ![Auto with a short list stays at 1 column](screenshots/auto-1col-short-list.png) | ![Auto with a workweek fits at 2 columns](screenshots/auto-2col-workweek.png) |

| Auto, 14 days (4 col) | Auto, 16 days (4 col) |
|---|---|
| ![Auto with a fortnight uses 4 columns](screenshots/auto-4col-fortnight.png) | ![Auto with 16 days still fits at 4 columns](screenshots/auto-4col-16days.png) |

## Install

Settings, Widgets, Browse community widgets, search "Calendar Schedule", Install. Restart Tesserae when prompted.

Make sure you have at least one feed configured in **Widgets → Calendar Feeds** (provided by `calendar_core`, ships bundled).

## Cell options

- **Days to show**: today only, 3 days, 5 days, a week, or two weeks.
- **Feed IDs**: restrict to specific feeds (comma-separated). Blank includes every enabled feed.
- **Hide events matching**: comma-separated words; any event whose title or location contains one is dropped. Case-insensitive and matches part of a word, so `lunch` hides "Lunch with Poppy". Useful for a recurring event you don't need on the panel.
- **Only show events matching**: the inverse, for when it's easier to say what you want than what you don't. Blank shows everything. Hide words still apply on top, so an event has to match this list and avoid that one.

  Both lists match against what the panel actually shows: with **Show event locations** off, locations aren't matched either, so a filter can't drop events for reasons you can't see on the screen.
- **Show event locations**: toggles the lighter-grey location text after the title.
- **Show per-feed colour dot**: turn off for pure typography (useful on 1-bit panels).
- **Time format**: Auto, 24-hour, or 12-hour.
- **Skip days with no events**: when off, every day in the window renders even if empty.
- **Max events per day**: cap each day's row count (0 = show all).
- **Layout columns**: flow the agenda across 1 to 4 vertical columns so a longer window (say two weeks) fits in a half-height cell without shrinking every row. Defaults to **Auto**, which starts at 1 and grows the column count only until the whole list fits; pick a fixed count (1-4) if you want to lock the layout. Days stay atomic (never split across columns); the browser packs by real content height, not day count.

Feed colour is carried by the start-time chip and the all-day bar. Turning off **Show per-feed colour dot** replaces the chip fill with ink for 1-bit panels.

### Sensible column defaults per panel

Leave it on **Auto** if you don't know what to pick. When you want to force a specific layout, the rough guide is:

| Panel                                  | Suggested `columns` |
|----------------------------------------|---------------------|
| ≤ 800 px wide (TRMNL, small mono)      | 1                   |
| 1200 wide portrait (E1004, EE02)       | 2                   |
| 1600 wide landscape (Inky 13.3")       | 2 or 3              |
| 1872 wide landscape (E1003, TRMNL X)   | 3                   |
| very wide desks / kiosks               | 4                   |

The multi-column flow reads column-first: day 1 top-left, day 2 below it, wrap to top of column 2 when column 1 fills.

## Layout

Each day is a header (big day number + weekday, muted month right-aligned) with a thick ink underline, followed by any all-day events as coloured bars, then a timeline rail of timed events. Each timed event has a coloured start-time chip on the left, a rail-node dot on a 2px vertical spine, and a wrapping title with `until <end time> · <location>` beneath. Days stay atomic across columns (never split).

```
6  MON                                                   JUL
[09:00] •  Standup
           until 09:30
[11:00] •  Design review with Alex
           until 12:00 · Studio A
[12:30] •  Lunch w/ Sam
           until 13:30 · Corner cafe

7  TUE                                                   JUL
[ ALL DAY  Public Holiday                                    ]
[08:00] •  Coffee walk
           until 08:30
```

The first day in the window is highlighted as "today" (accent-coloured day number).

## Timezone handling

Day grouping happens server-side using your **Settings → Timezone** setting, so an event at 23:00 UTC on Wed renders under Thu's bucket for a user in Europe/Berlin (UTC+2). Time strings ("3:45 – 4:45pm") are formatted client-side, also in that zone (Tesserae 0.44.10+ forwards the setting to the rendering Chromium so the device frame matches the preview).

## What you need

- `calendar_core` plugin installed (ships bundled with Tesserae).
- At least one iCal feed configured in **Widgets → Calendar Feeds**. Google Calendar / iCloud / Outlook all expose private iCal URLs you can paste.
- Tesserae's renderer reaches the iCal URL(s) you configured. The widget's network access goes through `calendar_core`'s `needs_network: true` block.

## Caveats

- Agenda layouts are text-dense by nature. At very small cell sizes (xs / sm), expect long event titles to truncate with an ellipsis and locations to be hidden. Increase `max_events_per_day` or pick a larger cell if you find it crowded.
- The screenshot reference uses Google's design language; the widget aims for a similar feel but inherits Tesserae's theme tokens (`--text-primary`, `--surface`, `--accent`) so it slots into whatever theme your dashboard uses.
- Recurring events expand server-side via `recurring_ical_events` (the same path the other calendar_* widgets use). Exceptions and EXDATEs are honoured.

## Licence

AGPL-3.0-or-later.
