from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from booking_guard.speech import classify_reply, clean_name, normalize_phone, say_phone, spell_name, time_words

THREE_PM = time_words(datetime(2026, 11, 18, 15, 0, tzinfo=ZoneInfo("America/New_York")))


@pytest.mark.parametrize("text", [
    "Yes", "yes.", "Yeah", "Yep, go ahead.", "Sure", "Okay, book it.", "That works.",
    "Sounds good", "Yes please", "Correct.", "That's right", "Perfect, thank you.",
    "Um, yes.", "Absolutely",
])
def test_plain_yes(text):
    assert classify_reply(text) == "yes"


@pytest.mark.parametrize("text", [
    "Yes, but can we do four instead?", "Maybe", "Hmm, let me think.", "I think so",
    "Not sure", "Yes? What day was that?", "What about Thursday?", "Okay, actually wait.",
    "Yes, and is there parking?", "", "Hold on", "Sure, but later in the day",
    "Probably", "Can you repeat that?", "No problem, yes",
])
def test_not_a_clear_yes(text):
    assert classify_reply(text) == "unclear"


@pytest.mark.parametrize("text", ["No", "Nope.", "No, that's too early.", "Nah", "That's wrong."])
def test_plain_no(text):
    assert classify_reply(text) == "no"


def test_yes_may_repeat_the_offered_time_but_not_another():
    assert classify_reply("Yes, three pm is fine.", THREE_PM) == "yes"
    assert classify_reply("Yes, Wednesday at 3 works.", THREE_PM) == "yes"
    assert classify_reply("Yes, four works.", THREE_PM) == "unclear"
    assert classify_reply("Yes, Thursday at three.", THREE_PM) == "unclear"


@pytest.mark.parametrize("spoken,digits", [
    ("212 555 0147", "2125550147"),
    ("(212) 555-0147", "2125550147"),
    ("two one two five five five oh one four seven", "2125550147"),
    ("six four six, five five five, oh one double nine", "6465550199"),
    ("+1 212 555 0147", "+12125550147"),
    ("plus one two one two five five five zero one four seven", "+12125550147"),
    ("my number is 212 555 0147", "2125550147"),
    ("triple five, 212, 0147", "5552120147"),
])
def test_phone_numbers_are_normalized(spoken, digits):
    assert normalize_phone(spoken) == digits


@pytest.mark.parametrize("spoken", [
    "212 555 014",                 # a digit missing
    "212 555 0147 0147 0147 01",   # too long
    "two one two five five five oh one four",
    "212 555 01four7 ext",         # a word that isn't a digit
    "double",                      # "double" with nothing after it
    "",
])
def test_bad_phone_numbers_are_refused(spoken):
    assert normalize_phone(spoken) is None


def test_phone_read_back_groups_digits():
    assert say_phone("2125550147") == "2 1 2, 5 5 5, 0 1 4 7"
    assert say_phone("+12125550147") == "plus 1, 2 1 2, 5 5 5, 0 1 4 7"


def test_names():
    assert clean_name("  dana   Whitfield ") == "dana Whitfield"
    assert clean_name("Mary-Jane O'Neil") == "Mary-Jane O'Neil"
    assert clean_name("José Álvarez") == "José Álvarez"
    assert clean_name("2125550147") is None
    assert clean_name("x") is None
    assert spell_name("Dana Whitfield") == "D-A-N-A, W-H-I-T-F-I-E-L-D"
