"""Turn what the caller said into checked values, and values into what the agent says.

Everything here is plain code with no model call, so the same input always
gives the same answer and every rule has a test.
"""

from __future__ import annotations

import re
from typing import Literal

Reply = Literal["yes", "no", "unclear"]

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_REPEAT_WORDS = {"double": 2, "triple": 3}
_FILLER = {"and", "uh", "um", "my", "number", "is", "it's", "its", "plus", "dash"}


def normalize_phone(spoken: str, min_digits: int = 10, max_digits: int = 15) -> str | None:
    """Return the number as digits (with a leading + if the caller gave one), or None.

    Accepts digits as the speech-to-text wrote them ("555-201-7788"), spoken
    digits ("five five five two oh one ..."), and "double"/"triple". Returns
    None when anything else is in the string or the digit count is outside
    min_digits..max_digits, so the agent asks again instead of guessing.
    """
    text = spoken.lower().strip()
    plus = text.startswith("+") or text.startswith("plus ")
    tokens = re.findall(r"[a-z']+|\d+|\+", text)
    digits: list[str] = []
    repeat = 1
    for tok in tokens:
        if tok == "+" or tok in _FILLER:
            continue
        if tok in _REPEAT_WORDS:
            repeat = _REPEAT_WORDS[tok]
            continue
        if tok.isdigit():
            chunk = tok
        elif tok in _DIGIT_WORDS:
            chunk = _DIGIT_WORDS[tok]
        else:
            return None
        if repeat > 1:
            chunk = chunk[0] * repeat + chunk[1:]
            repeat = 1
        digits.append(chunk)
    if repeat > 1:
        return None
    number = "".join(digits)
    if not (min_digits <= len(number) <= max_digits):
        return None
    return ("+" if plus else "") + number


def say_phone(number: str) -> str:
    """Read a number back digit by digit, in groups: '5 5 5, 2 0 1, 7 7 8 8'."""
    plus = number.startswith("+")
    d = number.lstrip("+")
    if len(d) == 10:
        sizes = [3, 3, 4]
    elif len(d) == 11:
        sizes = [1, 3, 3, 4] if d.startswith("1") else [4, 3, 4]
    else:
        sizes = [3] * (len(d) // 3)
        if len(d) % 3:
            sizes.append(len(d) % 3)
    groups, i = [], 0
    for size in sizes:
        groups.append(" ".join(d[i:i + size]))
        i += size
    return ("plus " if plus else "") + ", ".join(groups)


_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")


def clean_name(name: str) -> str | None:
    """Return the name with tidy spacing, or None if it isn't a plausible name."""
    tidy = " ".join(name.split())
    if not (2 <= len(tidy) <= 60) or not _NAME_RE.match(tidy):
        return None
    return tidy


def spell_name(name: str) -> str:
    """'Aisha Khan' -> 'A-I-S-H-A, K-H-A-N'."""
    return ", ".join("-".join(ch.upper() for ch in part if ch.isalpha()) for part in name.split())


# A yes must be plain. Any doubt, change of mind or question makes it unclear,
# and the agent asks again. Asking twice costs a few seconds; a wrong booking
# costs a missed appointment.
_YES = {
    "yes", "yeah", "yep", "yup", "yea", "sure", "correct", "right", "ok", "okay",
    "alright", "confirm", "confirmed", "absolutely", "definitely", "perfect",
    "great", "fine", "good", "exactly",
}
# Words that may sit around a yes without changing it ("yes please, book it").
_FILLER_OK = {
    "please", "go", "ahead", "book", "it", "that", "that's", "is", "sounds", "works",
    "for", "me", "do", "try", "again", "thanks", "thank", "you", "uh", "um", "all", "very", "much",
}
_YES_PHRASES = ("sounds good", "that works", "go ahead", "book it", "please do", "works for me")
_NO = {"no", "nope", "nah", "not", "don't", "dont", "wrong", "incorrect", "cancel", "never"}


def classify_reply(utterance: str, also_ok: frozenset[str] = frozenset()) -> Reply:
    """Classify the caller's answer to a yes/no question.

    "yes" only when every word is a yes word, filler, or one of `also_ok`
    (the words of the time that was offered, so "yes, three is fine" counts
    for 3:00 PM but "yes, four works" doesn't). A question, a "no" word or
    anything else makes it unclear ("yes, but at four", "maybe", "what about
    Thursday?", "not sure"). "no" when the answer has a no word and no yes word.
    """
    text = utterance.lower().strip()
    if not text:
        return "unclear"
    words = re.findall(r"[a-z']+", text)
    has_no = any(w in _NO for w in words)
    has_yes = any(w in _YES for w in words) or any(p in text for p in _YES_PHRASES)
    if has_no and not has_yes and "?" not in text:
        return "no"
    if has_no or "?" in text:
        return "unclear"
    if has_yes and all(w in _YES or w in _FILLER_OK or w in also_ok for w in words):
        return "yes"
    return "unclear"


_HOUR_WORDS = ["twelve", "one", "two", "three", "four", "five", "six", "seven",
               "eight", "nine", "ten", "eleven"]


def time_words(when) -> frozenset[str]:
    """Words a caller may use to repeat an offered time back: 'yes, Wednesday at three pm'."""
    hour12 = when.hour % 12
    words = {
        when.strftime("%A").lower(), when.strftime("%B").lower(), str(when.day),
        str(hour12 or 12), _HOUR_WORDS[hour12], "am" if when.hour < 12 else "pm", "a", "p", "m",
        "at", "on", "the", "o'clock", "is", "in", "morning" if when.hour < 12 else "afternoon",
        f"{hour12 or 12}:{when.minute:02d}",
    }
    if when.minute == 30:
        words |= {"30", "thirty", "half", "past"}
    elif when.minute == 0:
        words |= {"00"}
    return frozenset(words)
