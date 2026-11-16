"""The guard as a LiveKit Agents `Agent` (livekit-agents 1.8).

Drop-in shape for an existing LiveKit + Telnyx SIP agent: keep your
`AgentSession` (STT, LLM, TTS, VAD) and your SIP setup, and start the session
with this agent instead of your current one. Your Google Calendar code goes in
an object with the three methods of `booking_guard.calendar.Calendar`.

Two things make the booking safe:
- `on_user_turn_completed` passes each final caller turn to the guard before
  the LLM sees it, so the guard judges the caller's own words, not the LLM's
  summary of them.
- Every tool returns "OK: ..." or "NOT DONE: ..." with the next step, so the
  LLM is told what to say instead of guessing.
"""

from __future__ import annotations

from datetime import datetime

from livekit.agents import Agent, function_tool, llm

from booking_guard.calendar import Calendar
from booking_guard.guard import BookingGuard, Business

INSTRUCTIONS = """You book appointments for {business} by phone. Keep replies short.
1. Ask for the caller's full name and phone number, then call save_caller_details.
2. Say the read-back the tool gives you, word for word, and wait. Then call confirm_caller_details.
3. Ask which day suits them, call list_slots, and offer one time with offer_slot.
4. Ask the question offer_slot gives you, word for word, and wait for the answer.
5. Call book_appointment only after the caller answers that question.
Never say a time is booked unless book_appointment returned OK. If a tool returns
NOT DONE, do what it says. Today is {today}."""


class BookingAgent(Agent):
    def __init__(self, biz: Business, calendar: Calendar, call_id: str, now: datetime) -> None:
        self.guard = BookingGuard(biz=biz, calendar=calendar, call_id=call_id, now=now)
        local_now = now.astimezone(biz.tz)
        super().__init__(
            instructions=INSTRUCTIONS.format(business=biz.name, today=f"{local_now:%A %Y-%m-%d}")
        )

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        self.guard.hear_caller(new_message.text_content or "")

    @function_tool
    async def save_caller_details(self, name: str, phone: str) -> str:
        """Save the caller's full name and phone number exactly as they said them.

        Args:
            name: The caller's full name.
            phone: The phone number as the caller said it.
        """
        return str(self.guard.save_caller_details(name, phone))

    @function_tool
    async def confirm_caller_details(self) -> str:
        """Call after the caller answers the read-back of their name and number."""
        return str(self.guard.confirm_caller_details())

    @function_tool
    async def list_slots(self, day: str) -> str:
        """List free appointment times on one day.

        Args:
            day: The day as YYYY-MM-DD.
        """
        return str(self.guard.list_slots(day))

    @function_tool
    async def offer_slot(self, slot_id: str) -> str:
        """Offer one listed time to the caller.

        Args:
            slot_id: A time id from list_slots, like 2026-11-24T15:00.
        """
        return str(self.guard.offer_slot(slot_id))

    @function_tool
    async def book_appointment(self, slot_id: str) -> str:
        """Book the time you last offered, after the caller has answered.

        Args:
            slot_id: The id of the time you offered.
        """
        return str(self.guard.book_appointment(slot_id))
