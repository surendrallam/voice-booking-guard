# voice-booking-guard

Booking rules for a LiveKit voice agent: read the caller's name and number back and get a yes before saving them, and book only the exact time the caller said yes to.

It targets two faults: the agent saves the caller's details wrong, and it books before the caller has confirmed the time. Here the LLM still runs the conversation, but code decides whether each tool call is allowed. The code judges the caller's own words from speech-to-text, not the LLM's summary of them.

It is a work sample: Python 3.12, livekit-agents 1.8 (tested with 1.8.12), a fictional clinic (Cedar Lane Dental), a fake calendar and 18 synthetic call transcripts. It has not been deployed or run on a real phone call. It needs no API keys, accounts or network to test.

## What it handles

Each row is a transcript in [`tests/transcripts/transcripts.json`](tests/transcripts/transcripts.json): the caller's turns as speech-to-text would give them, and the tool calls an LLM made, including the wrong ones.

| Situation | Result | Transcript |
|---|---|---|
| Normal call | Details read back and confirmed, one time offered, yes, one booking | `01_happy_path` |
| LLM offers a time and books it in the same turn | Refused until the caller answers | `02_books_in_same_turn_as_offer` |
| Caller says "Hmm, maybe, let me think" | Refused; the time must be asked again | `03_books_on_maybe` |
| "Yes, but can we do four instead?" | Not a yes to three; four is offered and booked | `04_yes_but_change` |
| Caller says yes to 3:00 PM, LLM books 3:30 PM | Refused: not the time offered | `05_books_a_different_slot` |
| "Yes." then "Actually wait, is there anything after lunch?" | Refused; the later time is offered and booked | `06_changes_mind_after_yes` |
| Caller says no | Refused; another time is offered | `07_caller_says_no` |
| Speech-to-text writes "Whitfeld" | The read-back spells it out, the caller corrects it, the booking has "Whitfield" | `08_misheard_name_corrected` |
| A digit of the phone number is lost | The 9-digit number is refused and the agent asks again | `09_phone_missing_a_digit` |
| "Six four six, five five five, oh one double nine" | Saved as 6465550199 and read back digit by digit | `10_spoken_number_with_double` |
| LLM skips the read-back and books | Refused until the details are confirmed | `11_books_before_details` |
| Caller agrees a time, then gives a new number | The yes to the new read-back can't book the time; the time is asked again | `12_new_number_after_time_agreed` |
| Someone else takes the time while the caller thinks | Refused, no double booking, another time is booked | `13_slot_taken_before_yes` |
| LLM calls `book_appointment` twice | One calendar event | `14_repeated_book_call` |
| LLM offers a time the calendar never listed | Refused | `15_invented_time` |
| Caller answers with a question, then "Okay thanks" to the answer | Neither is a yes to the time; it is asked again | `16_question_is_not_a_yes` |
| Calendar call fails | "Not done" to the LLM, nothing reported as booked; the retry books once | `17_calendar_down` |
| Weekend, past day, or a day that isn't a date | No times offered | `18_closed_or_past_day` |

73 tests in all: the 18 transcripts, 2 checks across all of them, 51 unit tests for the yes/no, phone and name rules, and 2 for the LiveKit wiring.

## How it works

1. **Five tools, one guard.** The LLM gets `save_caller_details`, `confirm_caller_details`, `list_slots`, `offer_slot` and `book_appointment`. Each one calls [`BookingGuard`](src/booking_guard/guard.py) and returns `OK: ...` or `NOT DONE: ...` with the exact next step, for example the read-back sentence to say.
2. **The caller's words come from speech-to-text.** [`BookingAgent.on_user_turn_completed`](src/booking_guard/livekit_agent.py) hands every final caller turn to the guard before the LLM replies. The LLM can't tell the guard the caller said yes.
3. **Details are read back and confirmed.** The phone number is turned into digits ("oh", "double nine" and "(212) 555-0147" all work) and refused if it has fewer than 10 or more than 15 digits. The name is spelled out letter by letter. `confirm_caller_details` passes only on a clear yes after that read-back.
4. **A yes counts only for the question asked last.** `book_appointment` needs the exact time from the last `offer_slot`, and every caller turn since that offer must be a clear yes. New details clear the offered time, so a yes to the read-back can never book a time.
5. **What counts as a yes** is in [`speech.py`](src/booking_guard/speech.py): yes words ("yes", "yeah", "sure", "that works") plus filler and the words of the offered time ("yes, three pm is fine"). Anything else is unclear: a question, "maybe", "but", "not sure", or a different time ("yes, four works" when three was offered). Unclear means the agent asks again; it never books.
6. **Booking is checked again at the last moment.** The guard asks the calendar whether the time is still free just before it inserts, sends a fixed event id per call and time, and remembers the booking, so a repeated call doesn't book twice. Google Calendar lets you choose the event id (lowercase a–v and 0–9, 5 to 1024 characters, unique per calendar), but its docs say a duplicate id may not be caught at creation, so the guard doesn't rely on it.

## Limits I would tell a client about

- **The yes/no rule is a word list, in English.** It errs toward asking again. Real calls will show phrases it marks unclear that are really a yes; each one is a one-word change and a test. Callers who answer in another language need their words added.
- **It doesn't fix speech-to-text.** It catches a short number and makes the caller hear their name spelled back, but a wrong digit in a full-length number is caught only if the caller notices it in the read-back.
- **One booking per call.** Rescheduling or cancelling in the same call is refused, not handled.
- **The free-time check before booking is one more calendar call.** With Google Calendar that is a freebusy or events lookup, so it adds a little delay before "You're booked".
- **The fake calendar** has weekday hours from 9:00 to 17:00 in 30-minute slots. The real one is your Google Calendar code behind three methods (`free_slots`, `is_free`, `insert`).
- **Not tested with a live LLM, phone line or room.** The tests replay scripted tool calls, including the mistakes an LLM makes, against the real rules.

## Run it

```bash
uv venv -p 3.12 && uv pip install -e ".[dev]"
.venv/bin/pytest -q
```

No keys, accounts or network needed after install.

## Fitting it into an existing LiveKit + Telnyx agent

Not done here, as it needs the real agent. The steps would be:

1. Wrap the working Google Calendar code in a class with `free_slots(day)`, `is_free(slot)` and `insert(event_id, slot, name, phone)`.
2. Add the guard to the existing agent: one `BookingGuard` per call, each final caller turn passed to it in `on_user_turn_completed`, and the agent's detail and booking tools routed through the five guard checks. Or start from `BookingAgent` and merge the existing prompt and tools into it. Either way the `AgentSession`, STT, LLM, TTS and the Telnyx SIP setup stay as they are.
3. Add the five steps in `INSTRUCTIONS` to the business's own prompt.
4. Replay a few real call recordings as transcripts in the same JSON format and add them to the tests.

## What I would check first in a booking agent

- Which code path actually creates the calendar event, and can the LLM reach it without the caller saying yes?
- Does the agent judge the caller's words, or the LLM's paraphrase of them?
- Are the name and number read back before they are saved, and is the number's length checked?
- What happens when the caller changes their mind, asks a question, or the calendar call fails?
- Do the tests cover those cases, or only the happy path?

## Layout

```
src/booking_guard/guard.py          the booking rules for one call
src/booking_guard/speech.py         yes/no, phone number, name and time-word rules
src/booking_guard/calendar.py       the calendar interface and the fake calendar
src/booking_guard/livekit_agent.py  the guard as a LiveKit Agents Agent with five tools
tests/transcripts/transcripts.json  18 synthetic calls
tests/                              pytest, offline
```

MIT licence.
