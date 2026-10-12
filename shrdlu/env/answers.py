"""Answer normalisation (protocol §5.3).

P0 answers are all closed-form: ``yes``/``no``, one attribute word, or a number.
So grading is a strict, testable comparison after normalisation — no free-text
matching anywhere.

An answer that is empty, refused (``I don't know``), or outside the accepted
vocabulary counts as **wrong**.  That is deliberate: the protocol requires the
testee to commit to an answer.

Interpretation is **context-dependent**.  ``0`` and ``1`` are both truth values
and numbers, so a context-free reading gets one of the two cases wrong: grade a
count of ``1`` and a bare ``1`` would be read as "yes".  Which vocabulary
applies is decided by what the question asked for, never by guessing.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

from ..questions import Answer

#: Accepted spellings for the two truth values.
TRUE_WORDS = ("yes", "y", "true", "t", "1", "yeah", "yep")
FALSE_WORDS = ("no", "n", "false", "f", "0", "nope")

#: Number words, for answerers that spell numbers out.
NUMBER_WORDS: Dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}

#: Colour spellings that mean the same thing.
COLOR_ALIASES: Dict[str, str] = {
    "gray": "grey",
    "grayish": "grey",
}

#: Size spellings that mean the same thing.
SIZE_ALIASES: Dict[str, str] = {
    "large": "big",
    "huge": "big",
    "bigger": "big",
    "little": "small",
    "tiny": "small",
    "smaller": "small",
}

#: Shape words that mean the same thing.  ``block`` and ``cube`` name the same
#: physical shape in this world.
KIND_ALIASES: Dict[str, str] = {
    "block": "cube",
    "blocks": "cube",
    "cubes": "cube",
    "square": "cube",
    "cubical": "cube",
    "cubic": "cube",
    "pyramids": "pyramid",
    "boxes": "box",
    "balls": "ball",
    "spheres": "ball",
    "sphere": "ball",
}

_PUNCT = re.compile(r"[.,!?;:\"'`]+")
_WHITESPACE = re.compile(r"\s+")


def clean(text: object) -> str:
    """Lower-case, strip punctuation, squeeze whitespace."""
    if text is None:
        return ""
    s = str(text).lower()
    s = _PUNCT.sub(" ", s)
    s = _WHITESPACE.sub(" ", s)
    return s.strip()


def canonical_word(word: str) -> str:
    """Map a spelling onto the canonical vocabulary word."""
    word = clean(word)
    if word in COLOR_ALIASES:
        return COLOR_ALIASES[word]
    if word in SIZE_ALIASES:
        return SIZE_ALIASES[word]
    if word in KIND_ALIASES:
        return KIND_ALIASES[word]
    return word


def as_bool(text: object) -> Optional[bool]:
    """The truth value this text states, or ``None`` if it does not state one."""
    s = clean(text)
    if s in TRUE_WORDS:
        return True
    if s in FALSE_WORDS:
        return False
    return None


def as_number(text: object) -> Optional[int]:
    """The number this text states, or ``None``."""
    s = clean(text)
    if s.isdigit():
        return int(s)
    return NUMBER_WORDS.get(s)


def as_word(text: object) -> Optional[str]:
    """A single attribute word, canonicalised, or ``None``."""
    s = clean(text)
    if not s or " " in s:
        return None
    return canonical_word(s)


def matches(answer_text: object, expected: Answer) -> bool:
    """True when ``answer_text`` states exactly what ``expected`` says.

    The expected answer's kind picks the vocabulary, which is what keeps ``0``
    and ``1`` from being read as the wrong sort of thing.
    """
    if expected.kind == "bool":
        got = as_bool(answer_text)
        return got is not None and got is expected.value
    if expected.kind == "count":
        got_number = as_number(answer_text)
        return got_number is not None and got_number == expected.value
    if expected.kind == "value":
        got_word = as_word(answer_text)
        return got_word is not None and got_word == canonical_word(str(expected.value))
    return False
