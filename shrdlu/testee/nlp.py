"""P0 English parser — the testee side's understanding.

This is the only place in the system that has to turn English into meaning.
The env generates questions from semantics, so it needs no parser; the testee
receives English and must recover the semantics itself.  That asymmetry is
deliberate (see docs/develop/开发进度.md §1.5).

The grammar is tiny and closed::

    question := "What color is" NP "?" | "How big is" NP "?" | "What shape is" NP "?"
              | "Is" NP "on" NP "?"
              | "Is" NP "on the table?" | "Is" NP "clear?" | "Is" NP "supported?"
              | "How many" NP "are" REL "?"
              | "Is there" NP REL "?"
              | "Are all" NP REL "?"
    command  := "Pick up" NP "." | "Put down" NP "."
              | "Put" NP ("on"|"onto") NP "."
    NP       := DET? ADJ* NOUN REL?
    REL      := "on" NP | "on the table"

Reading is done by *attempting* a reading and accepting it only if it consumes
the whole input; failures restore the cursor and the next reading is tried.
That is what lets "Is the cube on the red cube clear?" be resolved: the first
reading leaves "clear" behind and is discarded, the second succeeds.

The quantifier is a surface detail: it affects rendering only, never
evaluation (``quant`` is normalised away for the counting question shapes).
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional, Tuple, TypeVar

from ..questions import AllQ, AttrQ, CountQ, Desc, ExistsQ, Question, Rel, RelQ

T = TypeVar("T")

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

KIND_WORDS = {
    "cube": "cube", "cubes": "cube", "block": "cube", "blocks": "cube",
    "pyramid": "pyramid", "pyramids": "pyramid",
    "ball": "ball", "balls": "ball", "sphere": "ball", "spheres": "ball",
}

COLOR_WORDS = {
    "red": "red", "green": "green", "blue": "blue", "yellow": "yellow",
    "white": "white", "black": "black", "brown": "brown", "orange": "orange",
    "purple": "purple", "grey": "grey", "gray": "grey", "pink": "pink",
    "cyan": "cyan", "magenta": "magenta",
}

SIZE_WORDS = {"big": "big", "large": "big", "small": "small", "little": "small"}

DETERMINERS = ("the", "a", "an", "all", "every", "this", "that")

PREPOSITIONS = {"on": "on", "onto": "on"}

#: Relations that take no object.
UNARY_RELATIONS = ("clear", "supported")

TERMINATORS = (".", "?", "!", ",")

_TOKEN = re.compile(r"[A-Za-z']+|\d+|[?.!,]")


class ParseError(Exception):
    """Raised when the input is outside the supported fragment."""

    def __init__(self, message: str, position: int = 0) -> None:
        super().__init__(message)
        self.position = position


def tokenize(text: str) -> List[str]:
    """Lower-case word tokens; punctuation kept as its own token."""
    return [t.lower() if t[:1].isalpha() else t for t in _TOKEN.findall(text or "")]


def neutral(desc: Desc) -> Desc:
    """Drop the surface quantifier, which never affects evaluation."""
    return Desc(quant="the", color=desc.color, size=desc.size, kind=desc.kind, rels=desc.rels)


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


class Parser:
    def __init__(self, text: str) -> None:
        self.tokens = tokenize(text)
        self.pos = 0

    # -- cursor ------------------------------------------------------------
    def peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        return self.tokens[index] if 0 <= index < len(self.tokens) else ""

    def take(self) -> str:
        word = self.peek()
        if word:
            self.pos += 1
        return word

    def accept(self, *words: str) -> bool:
        if self.peek() in words:
            self.pos += 1
            return True
        return False

    def expect(self, *words: str) -> str:
        word = self.peek()
        if word in words:
            self.pos += 1
            return word
        raise ParseError("expected %s, found %r" % (" or ".join(map(repr, words)), word), self.pos)

    def complete(self) -> bool:
        """True when only terminators remain."""
        return not [t for t in self.tokens[self.pos:] if t not in TERMINATORS]

    def attempt(self, builder: Callable[[], T]) -> Optional[T]:
        """Run one reading; keep it only if it consumes the whole input."""
        save = self.pos
        try:
            candidate = builder()
        except ParseError:
            self.pos = save
            return None
        if candidate is None or not self.complete():
            self.pos = save
            return None
        self.accept(*TERMINATORS)
        return candidate

    def finish(self) -> None:
        self.accept(*TERMINATORS)
        if not self.complete():
            raise ParseError("unexpected %r" % self.peek(), self.pos)

    # -- noun phrases ------------------------------------------------------
    def parse_np(self, allow_rel: bool = True) -> Optional[Desc]:
        start = self.pos
        quant = "the"
        if self.accept(*DETERMINERS):
            word = self.tokens[start]
            if word in ("all", "every"):
                quant = "all"
            elif word in ("a", "an"):
                quant = "a"

        color = size = kind = None
        while True:
            word = self.peek()
            if word in SIZE_WORDS:
                size = SIZE_WORDS[word]
            elif word in COLOR_WORDS:
                color = COLOR_WORDS[word]
            elif word in KIND_WORDS:
                kind = KIND_WORDS[word]
                self.take()
                break
            else:
                break
            self.take()

        if kind is None:
            self.pos = start
            return None

        rels: Tuple[Rel, ...] = ()
        if allow_rel:
            rel = self.try_parse_rel_phrase()
            if rel is not None:
                rels = (rel,)
        return Desc(quant=quant, color=color, size=size, kind=kind, rels=rels)

    def np(self, allow_rel: bool = True) -> Desc:
        desc = self.parse_np(allow_rel=allow_rel)
        if desc is None:
            raise ParseError("expected a noun phrase", self.pos)
        return desc

    def try_parse_rel_phrase(self) -> Optional[Rel]:
        save = self.pos
        word = self.peek()
        if word not in PREPOSITIONS:
            return None
        prep = PREPOSITIONS[word]
        self.take()

        # "on the table" is a unary relation, not a reference to an object:
        # the table is not one of the manipulable objects.
        if self.peek() == "the" and self.peek(1) == "table":
            self.take()
            self.take()
            if prep == "on":
                return Rel("on_table")
            self.pos = save
            return None

        target = self.parse_np(allow_rel=True)
        if target is None:
            self.pos = save
            return None
        return Rel(prep, target)

    def rel_phrase(self, allow_unary: bool = True) -> Rel:
        """A question predicate: a prepositional phrase, or a unary property.

        A noun phrase may only be modified by a prepositional phrase, so the
        "is X on Y" reading passes ``allow_unary=False`` to keep the two
        readings distinct.
        """
        if allow_unary and self.peek() in UNARY_RELATIONS:
            return Rel(self.take())
        rel = self.try_parse_rel_phrase()
        if rel is None:
            raise ParseError("expected a relation phrase", self.pos)
        return rel

    # -- question readings -------------------------------------------------
    def parse_question(self) -> Question:
        for builder in (
            self._q_attr,
            self._q_rel_on_in,
            self._q_rel_nested,
            self._q_rel_unary,
            self._q_count,
            self._q_exists,
            self._q_all,
        ):
            result = self.attempt(builder)
            if result is not None:
                return result
        raise ParseError("not a question I understand: %r" % (self.peek(),), self.pos)

    def _q_attr(self) -> Question:
        if self.accept("what", "which"):
            word = self.take()
            if word in ("color", "colour"):
                attribute = "color"
            elif word == "shape":
                attribute = "kind"
            elif word == "size":
                attribute = "size"
            else:
                raise ParseError("expected color/shape/size, found %r" % (word,), self.pos)
            self.accept("is", "are")
            return AttrQ(self.np(), attribute)

        self.expect("how")
        if not self.accept("big", "large", "tall", "wide"):
            raise ParseError("expected an adjective after 'how'", self.pos)
        self.accept("is", "are")
        return AttrQ(self.np(), "size")

    def _q_rel_on_in(self) -> Question:
        self.expect("is")
        desc = self.np(allow_rel=False)
        return RelQ(desc, self.rel_phrase(allow_unary=False))

    def _q_rel_nested(self) -> Question:
        """A relation question whose subject is itself relational.

        "Is the green cube on the red cube on the table?" — the noun phrase
        carries one relation, the question asks about another.
        """
        self.expect("is")
        desc = self.np(allow_rel=True)
        if not desc.rels:
            raise ParseError("the noun phrase carries no relation", self.pos)
        return RelQ(desc, self.rel_phrase(allow_unary=False))

    def _q_rel_unary(self) -> Question:
        self.expect("is")
        desc = self.np(allow_rel=True)
        word = self.expect("clear", "supported")
        return RelQ(desc, Rel(word))

    def _q_count(self) -> Question:
        self.expect("how")
        self.expect("many", "much")
        return self._set_question("count")

    def _q_exists(self) -> Question:
        self.expect("is")
        self.expect("there")
        return self._set_question("exists")

    def _q_all(self) -> Question:
        self.expect("are")
        self.expect("all", "every")
        return self._set_question("all")

    def _set_question(self, kind: str) -> Question:
        """Read the rest of a set question, trying both NP readings.

        "How many cubes are on the table?" puts the relation at question
        level; "How many cubes on the red cube are on the table?" puts one
        inside the noun phrase as well.  Both are generated, so both must be
        readable — the completeness check picks the right one.
        """
        for tail in (self._set_tail_plain, self._set_tail_relational):
            result = self.attempt(lambda tail=tail: tail(kind))
            if result is not None:
                return result
        raise ParseError("could not read the question", self.pos)

    def _set_tail_plain(self, kind: str) -> Question:
        desc = self.np(allow_rel=False)
        self.accept("are", "is")
        return self._make_set_question(kind, desc, self.rel_phrase())

    def _set_tail_relational(self, kind: str) -> Question:
        desc = self.np(allow_rel=True)
        if not desc.rels:
            raise ParseError("the noun phrase carries no relation", self.pos)
        self.accept("are", "is")
        return self._make_set_question(kind, desc, self.rel_phrase())

    @staticmethod
    def _make_set_question(kind: str, desc: Desc, rel: Rel) -> Question:
        desc = neutral(desc)
        if kind == "count":
            return CountQ(desc, rel)
        if kind == "exists":
            return ExistsQ(desc, rel)
        return AllQ(desc, rel)

    # -- command readings --------------------------------------------------
    def parse_command(self) -> Tuple[str, List[Desc]]:
        return self.attempt(self._c_command) or self._fail_command()

    def _fail_command(self):
        raise ParseError("not a command I understand: %r" % (self.peek(),), self.pos)

    def _c_command(self) -> Tuple[str, List[Desc]]:
        if self.accept("pick"):
            self.expect("up")
            return "pick_up", [self.np()]

        self.expect("put")
        if self.accept("down"):
            return "put_down", [self.np()]

        source = self.np(allow_rel=False)
        self.expect("on", "onto")
        target = self.np()
        return "put_on", [source, target]


# --------------------------------------------------------------------------
# Convenience
# --------------------------------------------------------------------------


def parse_question(text: str) -> Question:
    return Parser(text).parse_question()


def parse_command(text: str) -> Tuple[str, List[Desc]]:
    return Parser(text).parse_command()
