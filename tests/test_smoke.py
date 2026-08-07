"""Smoke tests for the calendar_schedule widget.

The widget composes calendar_core's ``load_events`` output into a
day-grouped agenda. We patch ``load_events`` so the tests don't reach
out to real ICS feeds, then assert on the day-grouping + sorting
logic that's unique to this widget.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server


def _stub_calendar_core(events: list[dict[str, Any]]) -> MagicMock:
    core = MagicMock()
    core.server_module.load_events.return_value = events
    core.data_dir = "/tmp/calendar_core_unused"
    return core


def _future_today_iso(hours: float) -> str:
    """Build an ISO timestamp ``hours`` from now in UTC. Used by tests
    that need a "today" event whose start / end are still in the future
    relative to the test run; without this the past-event filter would
    drop them if the wall clock has advanced past the hardcoded time."""
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def _stub_app(tz_setting: str = "UTC") -> MagicMock:
    """Stub of ``flask.current_app`` with the minimum config the widget
    reads: plugin registry + settings store."""
    settings = MagicMock()
    settings.get_section.return_value = {"timezone": tz_setting}
    registry = MagicMock()
    # ``registry.get`` returns the stubbed core when the widget asks for it.
    core = _stub_calendar_core([])
    registry.get.return_value = core
    app = MagicMock()
    app.config = {
        "PLUGIN_REGISTRY": registry,
        "SETTINGS_STORE": settings,
    }
    return app, registry, core, settings


def test_fetch_returns_empty_days_when_no_events() -> None:
    """No events anywhere -> ``days`` is empty by default
    (``skip_empty_days=True``)."""
    app, _registry, _core, _settings = _stub_app()
    with patch.object(server, "current_app", app):
        out = server.fetch(
            options={"days_ahead": "5"},
            settings={},
            ctx={},
        )
    assert "error" not in out
    assert out["days"] == []
    assert out["count"] == 0


def test_fetch_groups_events_into_today_and_tomorrow() -> None:
    """Two events on consecutive days land in their own day buckets,
    sorted with all-day at the top."""
    app, _registry, core, _settings = _stub_app()
    today = datetime.now(UTC).date()
    tomorrow = today + timedelta(days=1)
    core.server_module.load_events.return_value = [
        {
            "summary": "Stand-up",
            "start": _future_today_iso(hours=1),
            "end": _future_today_iso(hours=2),
            "all_day": False,
            "feed_name": "Work",
            "feed_colour": "#3366CC",
            "location": "Zoom",
        },
        {
            "summary": "Book fair",
            "start": tomorrow.isoformat(),
            "end": tomorrow.isoformat(),
            "all_day": True,
            "feed_name": "School",
            "feed_colour": "#22AA88",
            "location": "",
        },
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(
            options={"days_ahead": "3"},
            settings={},
            ctx={},
        )
    assert "error" not in out
    assert len(out["days"]) == 2
    assert out["days"][0]["is_today"] is True
    assert out["days"][0]["events"][0]["summary"] == "Stand-up"
    assert out["days"][0]["events"][0]["all_day"] is False
    assert out["days"][1]["is_tomorrow"] is True
    assert out["days"][1]["events"][0]["all_day"] is True
    assert out["count"] == 2


def test_past_timed_event_drops_off_today_after_it_ends() -> None:
    """A lunch 12:00 to 13:30 stops appearing on today's bucket once
    13:30 has passed. Without this filter the agenda gets cluttered
    with events that have already happened."""
    app, _registry, core, _settings = _stub_app()
    now = datetime.now(UTC)
    # Event that started two hours ago and ended one hour ago.
    started = now - timedelta(hours=2)
    ended = now - timedelta(hours=1)
    core.server_module.load_events.return_value = [
        {
            "summary": "Lunch with Fred",
            "start": started.isoformat(),
            "end": ended.isoformat(),
            "all_day": False,
        },
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(options={"days_ahead": "5"}, settings={}, ctx={})
    assert out["count"] == 0
    assert out["days"] == []


def test_currently_running_timed_event_still_shows() -> None:
    """An event that started before now but ends in the future is still
    happening, so it should still appear on today's bucket."""
    app, _registry, core, _settings = _stub_app()
    now = datetime.now(UTC)
    # Started one hour ago, ends in one hour.
    started = now - timedelta(hours=1)
    ending = now + timedelta(hours=1)
    core.server_module.load_events.return_value = [
        {
            "summary": "Conference call",
            "start": started.isoformat(),
            "end": ending.isoformat(),
            "all_day": False,
        },
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(options={"days_ahead": "5"}, settings={}, ctx={})
    assert out["count"] == 1
    assert out["days"][0]["events"][0]["summary"] == "Conference call"


def test_multi_day_all_day_event_spans_every_day_it_covers() -> None:
    """A holiday from Friday to Sunday (3 days) should land in Friday,
    Saturday, and Sunday's buckets, not just Friday. iCal carries the
    end as the exclusive Monday-00:00, which we detect and back off."""
    app, _registry, core, _settings = _stub_app()
    today = datetime.now(UTC).date()
    # Friday-to-Sunday holiday starting today. iCal end is Monday-00:00.
    fri = today
    mon_exclusive = today + timedelta(days=3)
    core.server_module.load_events.return_value = [
        {
            "summary": "Long weekend",
            "start": fri.isoformat(),
            "end": (mon_exclusive).isoformat(),
            "all_day": True,
        },
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(options={"days_ahead": "5"}, settings={}, ctx={})
    # Three days of buckets each carrying the same event.
    summaries_per_day = [[e["summary"] for e in d["events"]] for d in out["days"]]
    assert summaries_per_day[:3] == [
        ["Long weekend"],
        ["Long weekend"],
        ["Long weekend"],
    ]
    assert out["count"] == 3


def test_multi_day_timed_event_spans_every_day() -> None:
    """A conference that starts Friday 09:00 and ends Sunday 17:00
    should appear on Friday, Saturday, and Sunday in the agenda."""
    app, _registry, core, _settings = _stub_app()
    today = datetime.now(UTC).date()
    fri_start = datetime.combine(today, time(9, 0), tzinfo=UTC)
    sun_end = datetime.combine(today + timedelta(days=2), time(17, 0), tzinfo=UTC)
    core.server_module.load_events.return_value = [
        {
            "summary": "PyCon",
            "start": fri_start.isoformat(),
            "end": sun_end.isoformat(),
            "all_day": False,
        },
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(options={"days_ahead": "5"}, settings={}, ctx={})
    summaries_per_day = [[e["summary"] for e in d["events"]] for d in out["days"][:3]]
    assert summaries_per_day == [["PyCon"], ["PyCon"], ["PyCon"]]
    assert out["count"] == 3


def test_fully_past_multi_day_all_day_event_filtered_out() -> None:
    """A holiday that ended yesterday no longer shows."""
    app, _registry, core, _settings = _stub_app()
    today = datetime.now(UTC).date()
    # Last week's long weekend, fully in the past.
    past_start = today - timedelta(days=7)
    past_end_exclusive = today - timedelta(days=4)  # ended Sun, end-exclusive Mon
    core.server_module.load_events.return_value = [
        {
            "summary": "Last week's holiday",
            "start": past_start.isoformat(),
            "end": past_end_exclusive.isoformat(),
            "all_day": True,
        },
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(options={"days_ahead": "5"}, settings={}, ctx={})
    assert out["count"] == 0


def test_multi_day_event_in_progress_only_shows_from_today_forward() -> None:
    """A holiday that started yesterday and ends tomorrow shows on
    today and tomorrow, not yesterday (yesterday isn't in the window)."""
    app, _registry, core, _settings = _stub_app()
    today = datetime.now(UTC).date()
    yest = today - timedelta(days=1)
    day_after_tomorrow_exclusive = today + timedelta(days=2)
    core.server_module.load_events.return_value = [
        {
            "summary": "Long weekend in progress",
            "start": yest.isoformat(),
            "end": day_after_tomorrow_exclusive.isoformat(),
            "all_day": True,
        },
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(options={"days_ahead": "5"}, settings={}, ctx={})
    # Today + tomorrow, not yesterday (out of window).
    assert out["count"] == 2
    assert out["days"][0]["is_today"] is True
    assert out["days"][0]["events"][0]["summary"] == "Long weekend in progress"
    assert out["days"][1]["events"][0]["summary"] == "Long weekend in progress"


def test_all_day_events_come_first_within_a_day() -> None:
    """The screenshot shows All-day events at the top of each day; the
    widget must sort them that way regardless of feed order."""
    app, _registry, core, _settings = _stub_app()
    today = datetime.now(UTC).date()
    core.server_module.load_events.return_value = [
        {
            "summary": "Morning meeting",
            "start": _future_today_iso(1),
            "end": _future_today_iso(2),
            "all_day": False,
            "feed_name": "Work",
            "feed_colour": "#000",
        },
        {
            "summary": "Public holiday",
            "start": today.isoformat(),
            "end": today.isoformat(),
            "all_day": True,
            "feed_name": "Holidays",
            "feed_colour": "#FF0",
        },
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(options={"days_ahead": "1"}, settings={}, ctx={})
    events = out["days"][0]["events"]
    assert events[0]["all_day"] is True
    assert events[0]["summary"] == "Public holiday"
    assert events[1]["all_day"] is False


def test_show_dot_color_off_omits_colour() -> None:
    """When show_dot_color is False, ``colour`` is None so the client
    renders a blank slot (preserves vertical alignment)."""
    app, _registry, core, _settings = _stub_app()
    core.server_module.load_events.return_value = [
        {
            "summary": "x",
            "start": _future_today_iso(1),
            "end": _future_today_iso(2),
            "all_day": False,
            "feed_name": "y",
            "feed_colour": "#abc",
        }
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(
            options={"days_ahead": "1", "show_dot_color": False},
            settings={},
            ctx={},
        )
    assert out["days"][0]["events"][0]["colour"] is None


def test_show_location_off_drops_location_field() -> None:
    app, _registry, core, _settings = _stub_app()
    core.server_module.load_events.return_value = [
        {
            "summary": "x",
            "start": _future_today_iso(1),
            "end": _future_today_iso(2),
            "all_day": False,
            "feed_name": "y",
            "feed_colour": "#abc",
            "location": "Hill Media Center",
        }
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(
            options={"days_ahead": "1", "show_location": False},
            settings={},
            ctx={},
        )
    assert "location" not in out["days"][0]["events"][0]


def test_max_events_per_day_truncates() -> None:
    app, _registry, core, _settings = _stub_app()
    core.server_module.load_events.return_value = [
        {
            "summary": f"event {i}",
            "start": _future_today_iso(1 + i),
            "end": _future_today_iso(2 + i),
            "all_day": False,
            "feed_name": "y",
            "feed_colour": "#abc",
        }
        for i in range(6)
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(
            options={"days_ahead": "1", "max_events_per_day": 3},
            settings={},
            ctx={},
        )
    assert len(out["days"][0]["events"]) == 3


def test_skip_empty_days_off_keeps_blank_buckets() -> None:
    """``skip_empty_days=False`` shows every day in the window, even
    when the day has no events. Matches the screenshot's "Mon -- no
    events but still listed" pattern (sort of, the screenshot only
    shows populated days; this is the explicit opt-out)."""
    app, _registry, _core, _settings = _stub_app()
    with patch.object(server, "current_app", app):
        out = server.fetch(
            options={"days_ahead": "3", "skip_empty_days": False},
            settings={},
            ctx={},
        )
    assert len(out["days"]) == 3
    for d in out["days"]:
        assert d["events"] == []


def test_columns_defaults_to_auto_and_survives_round_trip() -> None:
    """v0.4.0: ``columns`` defaults to ``"auto"``. The client grows the
    column count 1..4 until the list fits; a fixed integer 1..4 skips
    that fit-loop and pins the layout. The server echoes the resolved
    value back so the client knows which mode to run in."""
    app, _registry, _core, _settings = _stub_app()
    with patch.object(server, "current_app", app):
        default_out = server.fetch(options={}, settings={}, ctx={})
        auto_out = server.fetch(options={"columns": "auto"}, settings={}, ctx={})
        two_col_out = server.fetch(options={"columns": "2"}, settings={}, ctx={})
        four_col_out = server.fetch(options={"columns": 4}, settings={}, ctx={})
    assert default_out["columns"] == "auto"
    assert auto_out["columns"] == "auto"
    assert two_col_out["columns"] == 2
    assert four_col_out["columns"] == 4


def test_columns_clamped_to_one_to_four() -> None:
    """Out-of-range or bad values fall through to the nearest valid
    bound (numeric) or auto (empty). Users can't crash the widget by
    typing ``9`` or ``"lots"`` in the picker."""
    app, _registry, _core, _settings = _stub_app()
    with patch.object(server, "current_app", app):
        assert (
            server.fetch(options={"columns": "9"}, settings={}, ctx={})["columns"] == 4
        )
        assert (
            server.fetch(options={"columns": "0"}, settings={}, ctx={})["columns"] == 1
        )
        assert (
            server.fetch(options={"columns": "lots"}, settings={}, ctx={})["columns"]
            == 1
        )
        # None / missing value falls through to auto (the default), not 1.
        assert (
            server.fetch(options={"columns": None}, settings={}, ctx={})["columns"]
            == "auto"
        )
        # Case-insensitive AUTO string; some UIs echo the option label back.
        assert (
            server.fetch(options={"columns": "AUTO"}, settings={}, ctx={})["columns"]
            == "auto"
        )


def test_missing_calendar_core_surfaces_error() -> None:
    """No calendar_core installed -> friendly error, no crash."""
    app = MagicMock()
    registry = MagicMock()
    registry.get.return_value = None
    app.config = {"PLUGIN_REGISTRY": registry, "SETTINGS_STORE": MagicMock()}
    with patch.object(server, "current_app", app):
        out = server.fetch(options={}, settings={}, ctx={})
    assert "error" in out
    assert "calendar_core" in out["error"]


def test_filter_window_excludes_events_outside_days_ahead() -> None:
    """Events more than ``days_ahead`` away get filtered out even
    though the core fetch's pad window included them. The widget
    should not surface a "day 8" event when days_ahead=3."""
    app, _registry, core, _settings = _stub_app()
    today = datetime.now(UTC).date()
    far_future = today + timedelta(days=8)
    core.server_module.load_events.return_value = [
        {
            "summary": "should not appear",
            "start": f"{far_future.isoformat()}T09:00:00+00:00",
            "end": f"{far_future.isoformat()}T10:00:00+00:00",
            "all_day": False,
            "feed_name": "y",
            "feed_colour": "#abc",
        }
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(options={"days_ahead": "3"}, settings={}, ctx={})
    assert out["count"] == 0
    assert out["days"] == []


def test_feeds_filter_parses_comma_separated_list() -> None:
    assert server._parse_feeds_filter("") is None
    assert server._parse_feeds_filter(" ") is None
    assert server._parse_feeds_filter("a,b,c") == ["a", "b", "c"]
    assert server._parse_feeds_filter("a , b,  c  ") == ["a", "b", "c"]
    assert server._parse_feeds_filter("a,,b") == ["a", "b"]


def test_max_events_total_caps_across_all_days() -> None:
    """A single busy day shouldn't shrink the agenda to fit. The
    total cap walks days in display order, fills until the budget runs
    out, and signals via ``truncated=True`` so the client can show the
    'capped' pill."""
    app, _registry, core, _settings = _stub_app()
    today = datetime.now(UTC).date()
    tomorrow = today + timedelta(days=1)
    core.server_module.load_events.return_value = [
        # Eight events today
        *[
            {
                "summary": f"today-{i}",
                "start": _future_today_iso(1 + i),
                "end": _future_today_iso(2 + i),
                "all_day": False,
                "feed_name": "y",
                "feed_colour": "#abc",
            }
            for i in range(8)
        ],
        # Two events tomorrow
        *[
            {
                "summary": f"tom-{i}",
                "start": f"{tomorrow.isoformat()}T{9 + i:02d}:00:00+00:00",
                "end": f"{tomorrow.isoformat()}T{10 + i:02d}:00:00+00:00",
                "all_day": False,
                "feed_name": "y",
                "feed_colour": "#abc",
            }
            for i in range(2)
        ],
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(
            options={"days_ahead": "2", "max_events_total": 5},
            settings={},
            ctx={},
        )
    # Total events across all days <= cap; today gets truncated, tomorrow drops.
    total = sum(len(d["events"]) for d in out["days"])
    assert total == 5
    assert out["truncated"] is True
    # First day still present and partially populated, second day dropped entirely.
    assert len(out["days"]) == 1
    assert len(out["days"][0]["events"]) == 5


def test_max_events_total_zero_means_no_cap() -> None:
    """0 leaves everything intact and never sets ``truncated``."""
    app, _registry, core, _settings = _stub_app()
    core.server_module.load_events.return_value = [
        {
            "summary": f"event-{i}",
            "start": _future_today_iso(1 + i),
            "end": _future_today_iso(2 + i),
            "all_day": False,
            "feed_name": "y",
            "feed_colour": "#abc",
        }
        for i in range(4)
    ]
    with patch.object(server, "current_app", app):
        out = server.fetch(
            options={"days_ahead": "1", "max_events_total": 0},
            settings={},
            ctx={},
        )
    assert sum(len(d["events"]) for d in out["days"]) == 4
    assert out["truncated"] is False


def test_show_title_defaults_to_true_and_is_forwarded() -> None:
    """``show_title`` lands in the payload unchanged so client.js can
    paint the chrome conditionally. Default is on (matches Spectra
    widget convention)."""
    app, _registry, _core, _settings = _stub_app()
    with patch.object(server, "current_app", app):
        default_out = server.fetch(options={"days_ahead": "1"}, settings={}, ctx={})
        off_out = server.fetch(
            options={"days_ahead": "1", "show_title": False}, settings={}, ctx={}
        )
    assert default_out["show_title"] is True
    assert off_out["show_title"] is False


# -- keyword filters (discussion #193) -------------------------------------


def _three_events() -> list[dict[str, Any]]:
    return [
        {
            "summary": "Lunch with Poppy",
            "start": _future_today_iso(1),
            "end": _future_today_iso(2),
            "all_day": False,
            "feed_name": "y",
            "feed_colour": "#abc",
            "location": "Cafe Rosa",
        },
        {
            "summary": "Dentist",
            "start": _future_today_iso(3),
            "end": _future_today_iso(4),
            "all_day": False,
            "feed_name": "y",
            "feed_colour": "#abc",
        },
        {
            "summary": "Standup",
            "start": _future_today_iso(5),
            "end": _future_today_iso(6),
            "all_day": False,
            "feed_name": "y",
            "feed_colour": "#abc",
            "location": "Cafe Rosa",
        },
    ]


def _titles(out: dict[str, Any]) -> list[str]:
    return [e["summary"] for d in out["days"] for e in d["events"]]


def _run(options: dict[str, Any]) -> dict[str, Any]:
    app, _registry, core, _settings = _stub_app()
    core.server_module.load_events.return_value = _three_events()
    with patch.object(server, "current_app", app):
        return server.fetch(options={"days_ahead": "1", **options}, settings={}, ctx={})


def test_hide_keywords_drops_matching_events() -> None:
    """The ask: hide a recurring "Lunch with Poppy" by typing "Lunch"."""
    assert _titles(_run({"hide_keywords": "lunch"})) == ["Dentist", "Standup"]


def test_hide_keywords_is_case_insensitive_and_matches_part_of_a_word() -> None:
    assert _titles(_run({"hide_keywords": "LUNCH"})) == ["Dentist", "Standup"]
    assert _titles(_run({"hide_keywords": "dent"})) == ["Lunch with Poppy", "Standup"]


def test_hide_keywords_accepts_several_terms() -> None:
    assert _titles(_run({"hide_keywords": "lunch, dentist"})) == ["Standup"]


def test_hide_keywords_matches_the_location_too() -> None:
    """Filtering on a place drops everything there without naming each event."""
    assert _titles(_run({"hide_keywords": "cafe rosa"})) == ["Dentist"]


def test_hide_keywords_ignores_the_location_when_locations_are_hidden() -> None:
    """Matching text the panel doesn't show would look like events vanishing
    for no reason."""
    out = _run({"hide_keywords": "cafe rosa", "show_location": False})
    assert _titles(out) == ["Lunch with Poppy", "Dentist", "Standup"]


def test_blank_and_comma_only_filters_change_nothing() -> None:
    """An empty term must not match every event and empty the agenda."""
    for value in ("", "   ", ",", " , , "):
        assert len(_titles(_run({"hide_keywords": value}))) == 3


def test_only_keywords_restricts_to_matches() -> None:
    assert _titles(_run({"only_keywords": "standup"})) == ["Standup"]


def test_only_and_hide_combine() -> None:
    """An event must match "only" and must not match "hide"."""
    out = _run({"only_keywords": "cafe rosa", "hide_keywords": "lunch"})
    assert _titles(out) == ["Standup"]
