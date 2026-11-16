"""Replay each synthetic call against the guard and a fake calendar.

Each transcript is a call as the voice pipeline sees it: final caller turns
from speech-to-text, and the tool calls a model made, including the wrong
ones. Each step checks whether the guard allowed the tool call; at the end
the calendar must hold exactly the expected bookings.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from booking_guard.calendar import FakeCalendar
from booking_guard.guard import BookingGuard, Business

TRANSCRIPTS = json.loads((Path(__file__).parent / "transcripts" / "transcripts.json").read_text())
TZ = ZoneInfo("America/New_York")
BIZ = Business(name="Cedar Lane Dental", tz=TZ, tz_spoken="Eastern time")
NOW = datetime(2026, 11, 17, 10, 0, tzinfo=TZ)  # Tuesday morning


def new_guard() -> tuple[BookingGuard, FakeCalendar]:
    cal = FakeCalendar(tz=TZ)
    return BookingGuard(biz=BIZ, calendar=cal, call_id="call-test", now=NOW), cal


@pytest.mark.parametrize("t", TRANSCRIPTS, ids=[t["id"] for t in TRANSCRIPTS])
def test_transcript(t: dict) -> None:
    guard, cal = new_guard()
    for n, step in enumerate(t["steps"]):
        where = f"{t['id']} step {n}: {step}"
        if "caller" in step:
            guard.hear_caller(step["caller"])
        elif "calendar" in step:
            if step["calendar"] == "block":
                cal.blocked.add(step["slot"])
            elif step["calendar"] == "fail_next_insert":
                cal.fail_next_insert = True
        else:
            before = len(cal.bookings)
            result = getattr(guard, step["tool"])(**step.get("args", {}))
            assert result.ok is step["ok"], f"{where}\n-> {result}"
            if "has" in step:
                assert step["has"] in result.say, f"{where}\n-> {result}"
            if not result.ok:
                assert len(cal.bookings) == before, f"{where}: a refused call changed the calendar"
            # The calendar never holds more than one booking from one call.
            assert len(cal.bookings) <= 1, where

    got = [{"slot": b.slot.id, "name": b.name, "phone": b.phone} for b in cal.bookings]
    assert got == t["bookings"]


def test_there_are_15_to_20_transcripts_covering_both_client_failures() -> None:
    assert 15 <= len(TRANSCRIPTS) <= 20
    failures = {t.get("client_failure") for t in TRANSCRIPTS}
    assert {"books before the time is confirmed", "caller details captured wrong"} <= failures


def test_every_booking_matches_the_last_offer_and_the_confirmed_details() -> None:
    """The invariant behind every transcript, checked on the guard's state after each call."""
    for t in TRANSCRIPTS:
        guard, cal = new_guard()
        for step in t["steps"]:
            if "caller" in step:
                guard.hear_caller(step["caller"])
            elif "calendar" in step:
                if step["calendar"] == "block":
                    cal.blocked.add(step["slot"])
                else:
                    cal.fail_next_insert = True
            else:
                getattr(guard, step["tool"])(**step.get("args", {}))
        for b in cal.bookings:
            assert guard.details_confirmed, t["id"]
            assert (b.name, b.phone) == (guard.name, guard.phone), t["id"]
            assert b.slot == guard.offered, t["id"]
