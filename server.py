"""calendar_schedule: Google-Calendar-style agenda view.

Lists upcoming events grouped by day with per-feed colour dots. Reads
from the same ``calendar_core`` feeds the other calendar_* widgets use.

Day grouping happens here, in the user's configured timezone, so an
event at 23:00 UTC on Wed renders under Thu's bucket for a user in
Europe/Berlin (UTC+2) the way the user expects. UTC ISO timestamps
still go out to the client unchanged so client.js can pick its own
locale-format for the time strings.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app


def _parse_feeds_filter(s: str) -> list[str] | None:
    s = (s or "").strip()
    if not s:
        return None
    return [x.strip() for x in s.split(",") if x.strip()]


def _parse_keywords(s: str) -> list[str]:
    """Comma-separated keywords, lowercased for case-insensitive matching.

    Blank entries are dropped so a trailing comma or a stray ", ," can't
    produce an empty term, which would otherwise match every event and
    silently empty the agenda."""
    return [k.strip().lower() for k in (s or "").split(",") if k.strip()]


def _matches_keyword(row: dict[str, Any], keywords: list[str]) -> bool:
    """Whether an event's title or location contains any keyword.

    Substring rather than whole-word: the request is to hide a recurring
    "Lunch with Poppy" by typing "Lunch", and people expect a fragment to
    work. Location is included so a filter can drop everything at a given
    place without listing each event."""
    haystack = f"{row.get('summary') or ''} {row.get('location') or ''}".lower()
    return any(k in haystack for k in keywords)


def _resolve_local_tz() -> ZoneInfo:
    """Read settings.app.timezone and return a ZoneInfo.

    v0.4.2 (r/eink launch DM feedback): when the app timezone is the
    literal ``"system"`` (fresh-install / onboarding default), the
    previous fallback to UTC caused day-grouping to skew. An 8:30 PM
    EDT event became 00:30 UTC the next calendar day, so the widget
    bucketed it under Tomorrow instead of Today. Tesserae's core
    ``app.tz_resolve.app_timezone()`` helper reads ``/etc/localtime``
    + the ``TZ`` env var to resolve ``"system"`` into a real IANA
    zone; delegate to it when it's importable, and fall back to UTC
    only when the widget can't reach the helper (standalone tests).
    """
    try:
        from app.tz_resolve import app_timezone

        resolved = app_timezone()
        if isinstance(resolved, ZoneInfo):
            return resolved
        key = getattr(resolved, "key", None)
        if isinstance(key, str) and key:
            return ZoneInfo(key)
    except Exception:
        pass
    try:
        store = current_app.config.get("SETTINGS_STORE")
        raw = ""
        if store is not None:
            raw = str(store.get_section("app").get("timezone") or "").strip()
        if not raw or raw.lower() == "system":
            return ZoneInfo("UTC")
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, Exception):
        return ZoneInfo("UTC")


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO string from calendar_core into an aware datetime
    (UTC if no tz info). All-day events arrive as plain ``YYYY-MM-DD``,
    which datetime.fromisoformat handles by returning a date; the
    caller converts to a datetime at midnight in the local zone."""
    try:
        if "T" in value:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        # Date-only string
        d = date.fromisoformat(value)
        return datetime.combine(d, time(0, 0))
    except (TypeError, ValueError):
        return None


def _local_date(dt: datetime, tz: ZoneInfo) -> date:
    if dt.tzinfo is None:
        return dt.date()
    return dt.astimezone(tz).date()


def _local_time_iso(dt: datetime, tz: ZoneInfo) -> str:
    """ISO with local-zone offset baked in so the client's ``new Date()``
    + ``toLocale...`` paints the wall-clock time directly without
    needing to apply its own offset."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz).isoformat()


def fetch(
    options: dict[str, Any], settings: dict[str, Any], *, ctx: dict[str, Any]
) -> dict[str, Any]:
    del settings, ctx
    registry = current_app.config["PLUGIN_REGISTRY"]
    core = registry.get("calendar_core")
    if core is None or core.server_module is None:
        return {"error": "calendar_core plugin not installed.", "days": []}

    # v0.4.3: ``days_ahead`` accepts an integer or the literal "fill"
    # (r/eink launch feedback, flinkazoid). ``fill`` pulls enough days
    # to fill most panel sizes; the client-side auto-column +
    # column-fill flow then paints as many as physically fit in the
    # cell without server-side guesswork about the panel size.
    # v0.4.4: dropped fill from 365 to 90 days — a full year of
    # recurring events (daily standup, weekly 1:1s) balloons out to
    # thousands of expanded instances via ``recurring_ical_events``
    # and made every render slow. 90 days still fills a 4-column
    # landscape panel comfortably.
    raw_days = str(options.get("days_ahead") or "").strip().lower()
    if raw_days == "fill":
        days_ahead = 90
    else:
        try:
            days_ahead = max(1, int(options.get("days_ahead") or 5))
        except (TypeError, ValueError):
            days_ahead = 5
    feeds_filter = _parse_feeds_filter(options.get("feeds_filter") or "")
    hide_keywords = _parse_keywords(options.get("hide_keywords") or "")
    only_keywords = _parse_keywords(options.get("only_keywords") or "")
    show_location = bool(options.get("show_location", True))
    show_dot_color = bool(options.get("show_dot_color", True))
    time_format = (options.get("time_format") or "auto").strip().lower()
    skip_empty_days = bool(options.get("skip_empty_days", True))
    try:
        max_per_day = max(0, int(options.get("max_events_per_day") or 0))
    except (TypeError, ValueError):
        max_per_day = 0
    try:
        max_total = max(0, int(options.get("max_events_total") or 0))
    except (TypeError, ValueError):
        max_total = 0
    show_title = bool(options.get("show_title", True))

    def _coerce_scale(name: str, default: float, lo: float, hi: float) -> float:
        try:
            v = float(options.get(name) if options.get(name) not in (None, "") else default)
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    event_title_scale = _coerce_scale("event_title_scale", 1.0, 0.7, 1.5)
    event_time_scale = _coerce_scale("event_time_scale", 1.0, 0.7, 1.5)
    event_location_scale = _coerce_scale("event_location_scale", 0.9, 0.6, 1.3)
    day_row_padding_em = _coerce_scale("day_row_padding_em", 0.5, 0.0, 1.5)
    # ``columns`` accepts the string "auto" (client grows 1..4 until the
    # list fits) or an integer 1..4 (fixed count). Anything else falls
    # back to auto.
    raw_columns = str(options.get("columns") or "auto").strip().lower()
    if raw_columns == "auto":
        columns: int | str = "auto"
    else:
        try:
            n = int(raw_columns)
        except ValueError:
            n = 1
        columns = max(1, min(4, n))

    tz = _resolve_local_tz()
    now_local = datetime.now(tz)
    # Pad the window by a day on each end to catch:
    #   * events on "today" whose local start is just past midnight
    #     UTC of the day before (e.g. 00:30 BST = 23:30 UTC prior day)
    #   * the last day's overnight events that end into day+1
    window_start_utc = (now_local - timedelta(days=1)).astimezone(UTC)
    window_end_utc = (now_local + timedelta(days=days_ahead + 1)).astimezone(UTC)
    try:
        events = core.server_module.load_events(
            feeds_filter,
            window_start_utc,
            window_end_utc,
            data_dir=Path(core.data_dir),
        )
    except Exception as err:
        return {"error": f"{type(err).__name__}: {err}", "days": []}

    today_local = now_local.date()
    # Pre-populate each day bucket so missing days appear in the right
    # order; we drop empty ones at the end if skip_empty_days is on.
    buckets: dict[date, list[dict[str, Any]]] = {
        today_local + timedelta(days=i): [] for i in range(days_ahead)
    }
    last_local_date = today_local + timedelta(days=days_ahead - 1)

    for ev in events:
        s_raw = ev.get("start")
        if not isinstance(s_raw, str):
            continue
        sdt = _parse_iso(s_raw)
        if sdt is None:
            continue
        all_day = bool(ev.get("all_day"))
        edt = _parse_iso(ev.get("end") or s_raw) if ev.get("end") else sdt
        if edt is None:
            edt = sdt

        # Past-event filter for timed events: a lunch 12:00-13:30 stops
        # showing on the day it happened once 13:30 is gone. Currently-
        # running events (started, not ended) stay visible. Multi-day
        # timed events whose final ``edt`` is also past get dropped here.
        if not all_day and edt < now_local:
            continue

        # Compute the local-date span. Multi-day events appear on every
        # day they span, not just the start day. iCal all-day events
        # use an EXCLUSIVE end-date (a "Fri to Sun" event arrives as
        # start=Fri end=Mon-00:00), so detect a clean-midnight end that
        # sits strictly after start and subtract one day.
        if all_day:
            start_local_date = sdt.date()
            end_local_date = edt.date() if edt > sdt else sdt.date()
            if end_local_date > start_local_date and edt.time() == time(0, 0):
                end_local_date -= timedelta(days=1)
        else:
            start_local_date = _local_date(sdt, tz)
            end_local_date = _local_date(edt, tz)

        # Past-event filter for all-day events: drop if the whole span
        # ends before today (yesterday's holiday stops showing as of
        # midnight rolling over).
        if all_day and end_local_date < today_local:
            continue

        row: dict[str, Any] = {
            "summary": ev.get("summary") or "(untitled)",
            "all_day": all_day,
            "colour": (ev.get("feed_colour") if show_dot_color else None),
            "feed_name": ev.get("feed_name") or "",
        }
        if show_location and ev.get("location"):
            row["location"] = ev.get("location")

        # Keyword filters. Matched against the event as the operator sees it,
        # so a location only counts when locations are being shown; filtering
        # on text that isn't on the panel would look like events vanishing for
        # no reason. "Only" wins over "hide" being empty: with both set, an
        # event must match "only" and must not match "hide".
        if only_keywords and not _matches_keyword(row, only_keywords):
            continue
        if hide_keywords and _matches_keyword(row, hide_keywords):
            continue
        if not all_day:
            row["start_local"] = _local_time_iso(sdt, tz)
            row["end_local"] = _local_time_iso(edt, tz)

        # Spread the event across every day in its span that falls
        # inside the visible window. ``first_day`` is clamped to today
        # so events that started before now (a long holiday already in
        # progress) only show forward from today, not retroactively.
        first_day = max(start_local_date, today_local)
        last_day = min(end_local_date, last_local_date)
        current = first_day
        while current <= last_day:
            buckets.setdefault(current, []).append(row)
            current += timedelta(days=1)

    days_out: list[dict[str, Any]] = []
    for offset in range(days_ahead):
        d = today_local + timedelta(days=offset)
        items = buckets.get(d) or []
        if skip_empty_days and not items:
            continue
        # All-day events first, then chronological by start.
        items.sort(key=lambda r: (not r["all_day"], r.get("start_local") or ""))
        if max_per_day > 0:
            items = items[:max_per_day]
        days_out.append(
            {
                "date_iso": d.isoformat(),
                "day_of_month": d.day,
                "day_of_week_short": d.strftime("%a").upper(),
                "month_short": d.strftime("%b").upper(),
                "is_today": d == today_local,
                "is_tomorrow": d == today_local + timedelta(days=1),
                "events": items,
            }
        )

    # Apply the across-all-days cap after per-day filtering + chronological
    # ordering. Walk days in display order, accumulating event counts;
    # truncate the day that hits the cap and drop subsequent days. Days
    # whose full event list survives stay intact.
    truncated = False
    if max_total > 0:
        running = 0
        capped: list[dict[str, Any]] = []
        for day in days_out:
            room = max_total - running
            if room <= 0:
                truncated = True
                break
            events = day["events"]
            if len(events) <= room:
                capped.append(day)
                running += len(events)
                continue
            capped.append({**day, "events": events[:room]})
            truncated = True
            break
        days_out = capped

    return {
        "now": now_local.isoformat(),
        "tz": str(tz),
        "time_format": time_format,
        "show_location": show_location,
        "show_dot_color": show_dot_color,
        "show_title": show_title,
        "columns": columns,
        "event_title_scale": event_title_scale,
        "event_time_scale": event_time_scale,
        "event_location_scale": event_location_scale,
        "day_row_padding_em": day_row_padding_em,
        "days": days_out,
        "count": sum(len(d["events"]) for d in days_out),
        "truncated": truncated,
    }
