"""The calendar the guard books into.

The client's Google Calendar code already works, so the guard only needs it
behind three methods. `FakeCalendar` is the in-memory stand-in the tests use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Slot:
    start: datetime  # timezone-aware
    minutes: int

    @property
    def id(self) -> str:
        """What the model passes back to the tools, e.g. '2026-11-24T15:00'."""
        return self.start.strftime("%Y-%m-%dT%H:%M")


@dataclass(frozen=True)
class Booking:
    event_id: str
    slot: Slot
    name: str
    phone: str


class Calendar(Protocol):
    def free_slots(self, day: date) -> list[Slot]: ...
    def is_free(self, slot: Slot) -> bool: ...
    def insert(self, event_id: str, slot: Slot, name: str, phone: str) -> None: ...


class CalendarError(Exception):
    """The calendar call failed. Nothing may be reported to the caller as booked."""


@dataclass
class FakeCalendar:
    """Working hours on weekdays, fixed-length slots, bookings kept in a list."""

    tz: ZoneInfo
    opens: time = time(9, 0)
    closes: time = time(17, 0)
    minutes: int = 30
    bookings: list[Booking] = field(default_factory=list)
    blocked: set[str] = field(default_factory=set)  # slot ids taken by someone else
    fail_next_insert: bool = False

    def _day_slots(self, day: date) -> list[Slot]:
        if day.weekday() >= 5:
            return []
        out, t = [], datetime.combine(day, self.opens, self.tz)
        end = datetime.combine(day, self.closes, self.tz)
        while t + timedelta(minutes=self.minutes) <= end:
            out.append(Slot(t, self.minutes))
            t += timedelta(minutes=self.minutes)
        return out

    def is_free(self, slot: Slot) -> bool:
        taken = {b.slot.id for b in self.bookings} | self.blocked
        return slot.id not in taken and slot in self._day_slots(slot.start.date())

    def free_slots(self, day: date) -> list[Slot]:
        return [s for s in self._day_slots(day) if self.is_free(s)]

    def insert(self, event_id: str, slot: Slot, name: str, phone: str) -> None:
        if self.fail_next_insert:
            self.fail_next_insert = False
            raise CalendarError("calendar unavailable")
        if any(b.event_id == event_id for b in self.bookings):
            return  # same id again: already there
        if not self.is_free(slot):
            raise CalendarError("slot already taken")
        self.bookings.append(Booking(event_id, slot, name, phone))
