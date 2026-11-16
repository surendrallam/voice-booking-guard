"""The booking rules for one call.

The model talks to the caller and decides which tool to call. This class
decides whether the call is allowed. It hears every final caller turn
straight from speech-to-text, so the model can't report a yes the caller
never said.

Rules:
1. Details first: name and phone are saved, read back, and confirmed by a
   clear yes from the caller after the read-back.
2. A slot can be offered only if the calendar listed it as free.
3. Booking needs the exact slot that was offered last, and every caller
   turn since that offer must be a clear yes.
4. A yes counts only for the question asked last. New details clear the
   offered slot, so a yes to the read-back can never book a time.
5. One booking per call; a repeated booking call doesn't book twice.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from booking_guard.calendar import Booking, Calendar, CalendarError, Slot
from booking_guard.speech import classify_reply, clean_name, normalize_phone, say_phone, spell_name, time_words


@dataclass(frozen=True)
class Result:
    ok: bool
    say: str  # what the tool returns to the model

    def __str__(self) -> str:
        return ("OK: " if self.ok else "NOT DONE: ") + self.say


@dataclass
class Business:
    name: str
    tz: ZoneInfo
    tz_spoken: str
    min_phone_digits: int = 10
    max_phone_digits: int = 15


def say_slot(slot: Slot, biz: Business) -> str:
    t = slot.start.astimezone(biz.tz)
    clock = t.strftime("%I:%M %p").lstrip("0")
    return f"{t:%A} {t.day} {t:%B} at {clock} {biz.tz_spoken}"


@dataclass
class BookingGuard:
    biz: Business
    calendar: Calendar
    call_id: str
    now: datetime
    caller_turns: list[str] = field(default_factory=list)

    name: str | None = None
    phone: str | None = None
    details_asked_at: int | None = None  # caller turn count when details were read back
    details_confirmed: bool = False

    listed: dict[str, Slot] = field(default_factory=dict)
    offered: Slot | None = None
    offered_at: int | None = None  # caller turn count when the slot was offered
    booking: Booking | None = None
    last_question: str | None = None  # "details" or "slot"

    # --- input from speech-to-text -------------------------------------------------

    def hear_caller(self, text: str) -> None:
        """Record one final caller turn. Call it from the voice pipeline, not from the model."""
        self.caller_turns.append(text)

    def _answer_since(self, asked_at: int | None, also_ok: frozenset[str] = frozenset()) -> str | None:
        """The caller's answer to a question: None (no answer yet), "yes", "no" or "unclear".

        "yes" only if every caller turn since the question is a clear yes. A
        yes followed by "actually, wait..." is unclear, and so is "what's your
        address?" followed by "okay thanks": the question must be asked again.
        """
        if asked_at is None or len(self.caller_turns) <= asked_at:
            return None
        verdicts = [classify_reply(t, also_ok) for t in self.caller_turns[asked_at:]]
        if verdicts[-1] == "no":
            return "no"
        return "yes" if all(v == "yes" for v in verdicts) else "unclear"

    # --- tools ---------------------------------------------------------------------

    def save_caller_details(self, name: str, phone: str) -> Result:
        clean = clean_name(name)
        if clean is None:
            return Result(False, "That doesn't look like a name. Ask the caller for their full name.")
        number = normalize_phone(phone, self.biz.min_phone_digits, self.biz.max_phone_digits)
        if number is None:
            return Result(
                False,
                f"The phone number isn't complete ({phone!r}). Ask the caller to say it again, "
                f"slowly, digit by digit.",
            )
        self.name, self.phone = clean, number
        self.details_confirmed = False
        self.details_asked_at = len(self.caller_turns)
        self.last_question = "details"
        self.offered = None  # the time must be offered again after new details
        return Result(
            True,
            f'Read this back and wait for the answer: "I have your name as {clean}, '
            f"spelled {spell_name(clean)}, and your number as {say_phone(number)}. "
            f'Is that right?" Then call confirm_caller_details.',
        )

    def confirm_caller_details(self) -> Result:
        if self.name is None:
            return Result(False, "No details saved yet. Ask for the name and phone number first.")
        if self.last_question != "details":
            return Result(False, "You asked about a time after the read-back. Read the details back again first.")
        verdict = self._answer_since(self.details_asked_at)
        if verdict is None:
            return Result(False, "The caller hasn't answered the read-back yet. Wait for their answer.")
        if verdict == "yes":
            self.details_confirmed = True
            return Result(True, "Details confirmed. Ask which day suits them, then call list_slots.")
        if verdict == "no":
            return Result(
                False,
                "The caller said the details are wrong. Ask what needs fixing, then call "
                "save_caller_details again with the corrected name and number.",
            )
        return Result(
            False,
            "That wasn't a clear yes. Call save_caller_details again and read the details back once more.",
        )

    def list_slots(self, day: str) -> Result:
        try:
            d = date.fromisoformat(day)
        except ValueError:
            return Result(False, f"{day!r} isn't a date. Pass the day as YYYY-MM-DD.")
        if d < self.now.astimezone(self.biz.tz).date():
            return Result(False, "That day has passed. Ask for another day.")
        slots = [s for s in self.calendar.free_slots(d) if s.start > self.now]
        if not slots:
            return Result(False, f"No free times on {d:%A %d %B}. Ask for another day.")
        for s in slots:
            self.listed[s.id] = s
        lines = ", ".join(f"{s.id} ({say_slot(s, self.biz)})" for s in slots)
        return Result(True, f"Free times: {lines}. Offer one or two with offer_slot.")

    def offer_slot(self, slot_id: str) -> Result:
        slot = self.listed.get(slot_id)
        if slot is None:
            return Result(False, f"{slot_id} wasn't listed as free. Call list_slots and offer one of those.")
        self.offered = slot
        self.offered_at = len(self.caller_turns)
        self.last_question = "slot"
        return Result(
            True,
            f'Ask exactly this and wait for the answer: "Shall I book {say_slot(slot, self.biz)} '
            f'for you?" Call book_appointment only after the caller says yes.',
        )

    def book_appointment(self, slot_id: str) -> Result:
        if self.booking is not None:
            if self.booking.slot.id == slot_id:
                return Result(True, f"Already booked for {say_slot(self.booking.slot, self.biz)}. Don't book again.")
            return Result(False, "This call already has a booking. Changing it isn't supported on this line.")
        if not self.details_confirmed:
            return Result(False, "The caller's name and number aren't confirmed. Read them back first.")
        if self.offered is None or self.offered.id != slot_id:
            return Result(
                False,
                f"{slot_id} isn't the time you last offered. Offer it with offer_slot and wait for a yes.",
            )
        spoken = say_slot(self.offered, self.biz)
        verdict = self._answer_since(self.offered_at, time_words(self.offered.start.astimezone(self.biz.tz)))
        if verdict is None:
            return Result(False, f'The caller hasn\'t answered yet. Ask "Shall I book {spoken}?" and wait.')
        if verdict == "no":
            self.offered = None
            return Result(False, "The caller said no. Ask which day or time suits them better.")
        if verdict == "unclear":
            return Result(
                False,
                f"That wasn't a clear yes to {spoken}. If they asked for a change, offer the new time. "
                f"Otherwise answer their question, then call offer_slot again to ask once more.",
            )
        slot = self.offered
        if not self.calendar.is_free(slot):
            self.offered = None
            self.listed.pop(slot.id, None)
            return Result(False, f"{spoken} was just taken. Say sorry, call list_slots and offer another time.")
        event_id = hashlib.sha256(f"{self.call_id}|{slot.id}".encode()).hexdigest()
        try:
            self.calendar.insert(event_id, slot, self.name, self.phone)
        except CalendarError:
            return Result(
                False,
                "The calendar didn't save the booking. Don't tell the caller it is booked. "
                "Say there was a problem and ask if they want you to try again.",
            )
        self.booking = Booking(event_id, slot, self.name, self.phone)
        return Result(True, f'Booked. Tell the caller: "You\'re booked for {spoken}."')
