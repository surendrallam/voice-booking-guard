"""The LiveKit wiring, offline: no room, no SIP, no model.

Checks that livekit-agents accepts the agent and its five tools, and that a
caller turn arriving through `on_user_turn_completed` is what the guard
judges.
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from livekit.agents import llm

from booking_guard.calendar import FakeCalendar
from booking_guard.guard import Business
from booking_guard.livekit_agent import BookingAgent

TZ = ZoneInfo("America/New_York")


def make_agent():
    cal = FakeCalendar(tz=TZ)
    biz = Business(name="Cedar Lane Dental", tz=TZ, tz_spoken="Eastern time")
    return BookingAgent(biz, cal, call_id="call-1", now=datetime(2026, 11, 17, 10, 0, tzinfo=TZ)), cal


def test_agent_registers_the_five_tools():
    agent, _ = make_agent()
    names = {t.info.name for t in agent.tools}
    assert names == {"save_caller_details", "confirm_caller_details", "list_slots", "offer_slot", "book_appointment"}
    assert "Cedar Lane Dental" in agent.instructions
    assert "Tuesday 2026-11-17" in agent.instructions


def test_caller_turns_reach_the_guard_and_gate_the_booking():
    agent, cal = make_agent()

    async def caller(text):
        msg = llm.ChatMessage(role="user", content=[text])
        await agent.on_user_turn_completed(llm.ChatContext.empty(), msg)

    async def call():
        out = [await agent.save_caller_details("Dana Whitfield", "212 555 0147")]
        await caller("Yes, that's right.")
        out.append(await agent.confirm_caller_details())
        out.append(await agent.list_slots("2026-11-18"))
        out.append(await agent.offer_slot("2026-11-18T15:00"))
        out.append(await agent.book_appointment("2026-11-18T15:00"))  # before the caller answers
        await caller("Yes please.")
        out.append(await agent.book_appointment("2026-11-18T15:00"))
        return out

    out = asyncio.run(call())
    assert [o.split(":")[0] for o in out] == ["OK", "OK", "OK", "OK", "NOT DONE", "OK"]
    assert [b.slot.id for b in cal.bookings] == ["2026-11-18T15:00"]
