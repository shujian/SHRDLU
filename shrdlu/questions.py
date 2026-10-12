"""P0 questions: semantics, English generation, and truth evaluation.

This module is the env side's whole question mechanism.  It has three jobs:

* **represent** a question as data (:class:`Desc`, :class:`Rel`, the ``*Q``
  classes) — no English involved;
* **generate** the English surface form (:func:`render`);
* **evaluate** it against the true state (:func:`evaluate`) to get the answer
  the env will grade against.

The env never parses a question: it generates them, so it already knows the
meaning.  Delegating the surface form to :func:`render` and the meaning to the
data structure keeps the two from drifting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from .world import Obj, World

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

#: Attributes an L1 question can ask about.
ATTRS = ("color", "size", "kind")

#: Nouns used to render a kind.
KIND_NOUN = {
    "cube": "cube",
    "pyramid": "pyramid",
    "ball": "ball",
    "table": "table",
}

#: Plural forms for "all" / "how many".
KIND_PLURAL = {
    "cube": "cubes",
    "pyramid": "pyramids",
    "ball": "balls",
    "table": "tables",
}


class QuestionError(Exception):
    """Raised when a question cannot be formed or evaluated."""


class ResolutionError(QuestionError):
    """Raised when a definite description does not pick out exactly one thing."""


# --------------------------------------------------------------------------
# Semantics
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Rel:
    """A predicate applied to one object.

    ``name`` is one of ``on`` / ``on_table`` / ``clear`` / ``supported``.
    ``on`` takes a ``target``; the others are unary.
    """

    name: str
    target: Optional["Desc"] = None

    def render(self) -> str:
        if self.name == "on_table":
            return "on the table"
        if self.name == "clear":
            return "clear"
        if self.name == "supported":
            return "supported"
        if self.target is None:
            raise QuestionError("relation %r needs a target" % self.name)
        return "%s %s" % (self.name, self.target.render())


@dataclass(frozen=True)
class Desc:
    """A noun phrase: quantifier + attributes + restrictive relations."""

    quant: str = "the"  # "the" | "a" | "all"
    color: Optional[str] = None
    size: Optional[str] = None
    kind: Optional[str] = None
    rels: Tuple[Rel, ...] = ()

    # -- rendering ---------------------------------------------------------
    def _adjective_phrase(self, plural: bool = False) -> str:
        bits: List[str] = []
        if self.size:
            bits.append(self.size)
        if self.color:
            bits.append(self.color)
        if self.kind:
            bits.append(KIND_PLURAL[self.kind] if plural else KIND_NOUN[self.kind])
        return " ".join(bits)

    def render(self) -> str:
        body = self._adjective_phrase()
        if self.quant == "all":
            phrase = "all %s" % self._adjective_phrase(plural=True)
        elif self.quant == "a":
            phrase = "%s %s" % (_article(body), body)
        else:
            phrase = "the %s" % body
        for rel in self.rels:
            phrase = "%s %s" % (phrase, rel.render())
        return phrase

    def render_bare_plural(self) -> str:
        """For "How many X are ...?": a bare plural with no article."""
        phrase = self._adjective_phrase(plural=True) or "things"
        for rel in self.rels:
            phrase = "%s %s" % (phrase, rel.render())
        return phrase


def _article(phrase: str) -> str:
    return "an" if phrase[:1].lower() in "aeiou" else "a"


@dataclass(frozen=True)
class AttrQ:
    """What color is X? / How big is X? / What shape is X?"""

    desc: Desc
    attr: str


@dataclass(frozen=True)
class RelQ:
    """Is X on Y? / Is X clear? / Is X supported?"""

    desc: Desc
    rel: Rel


@dataclass(frozen=True)
class CountQ:
    """How many X are Y?"""

    desc: Desc
    rel: Rel


@dataclass(frozen=True)
class ExistsQ:
    """Is there an X that is Y?"""

    desc: Desc
    rel: Rel


@dataclass(frozen=True)
class AllQ:
    """Are all X Y?"""

    desc: Desc
    rel: Rel


Question = Union[AttrQ, RelQ, CountQ, ExistsQ, AllQ]


# --------------------------------------------------------------------------
# Answers
# --------------------------------------------------------------------------


@dataclass
class Answer:
    """The truth value of a question, in canonical form."""

    kind: str  # "bool" | "value" | "count"
    value: object

    def text(self) -> str:
        if self.kind == "bool":
            return "yes" if self.value else "no"
        return str(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Answer):
            return self.kind == other.kind and self.value == other.value
        return NotImplemented

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Answer(%s, %r)" % (self.kind, self.value)


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


def candidates(world: World, desc: Desc) -> List[Obj]:
    """Every object matching the descriptive content, ignoring the quantifier."""
    out: List[Obj] = []
    for obj in world.actual_objects():
        if desc.kind and obj.kind != desc.kind:
            continue
        if desc.color and obj.color != desc.color:
            continue
        if desc.size and obj.size != desc.size:
            continue
        if all(_matches(world, obj, rel) for rel in desc.rels):
            out.append(obj)
    return out


def _matches(world: World, obj: Obj, rel: Rel) -> bool:
    if rel.name == "on_table":
        return world.pos_of(obj)[0] == "table"
    if rel.name == "clear":
        return world.is_clear(obj)
    if rel.name == "supported":
        return world.is_supported(obj)
    if rel.name == "on":
        if rel.target is None:
            raise QuestionError("relation %r needs a target" % rel.name)
        for other in candidates(world, rel.target):
            pos = world.pos_of(obj)
            if pos[0] == rel.name and pos[1] == other.ident:
                return True
        return False
    raise QuestionError("unknown relation %r" % rel.name)


def unique(world: World, desc: Desc) -> Obj:
    """Resolve a definite description, which must pick out exactly one object."""
    found = candidates(world, desc)
    if not found:
        raise ResolutionError("nothing matches %r" % desc.render())
    if len(found) > 1:
        raise ResolutionError(
            "%r matches %d objects: %s"
            % (desc.render(), len(found), ", ".join(o.ident for o in found))
        )
    return found[0]


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def evaluate(question: Question, world: World) -> Answer:
    """The answer the env will grade against, computed from the true state."""
    if isinstance(question, AttrQ):
        if question.attr not in ATTRS:
            raise QuestionError("unknown attribute %r" % question.attr)
        obj = unique(world, question.desc)
        return Answer("value", getattr(obj, question.attr))

    if isinstance(question, RelQ):
        obj = unique(world, question.desc)
        return Answer("bool", _matches(world, obj, question.rel))

    if isinstance(question, CountQ):
        return Answer("count", sum(1 for o in candidates(world, question.desc)
                                   if _matches(world, o, question.rel)))

    if isinstance(question, ExistsQ):
        return Answer("bool", any(_matches(world, o, question.rel)
                                  for o in candidates(world, question.desc)))

    if isinstance(question, AllQ):
        found = candidates(world, question.desc)
        if not found:
            raise ResolutionError("nothing matches %r" % question.desc.render())
        return Answer("bool", all(_matches(world, o, question.rel) for o in found))

    raise QuestionError("unknown question type %r" % type(question).__name__)


def validate_desc(desc: Desc, world: World) -> Optional[str]:
    """Return a reason when a description does not pick out exactly one object."""
    try:
        unique(world, desc)
    except QuestionError as exc:
        return str(exc)
    return None


def validate(question: Question, world: World) -> Optional[str]:
    """Return a reason string when the question is not fit to be asked.

    A question is unfit when a definite description is empty or ambiguous
    (protocol §2.1), or when an "all" question has nothing to range over.
    Such questions must be dropped by the question generator and are never
    counted in the denominator.
    """
    try:
        evaluate(question, world)
    except ResolutionError as exc:
        return str(exc)
    except QuestionError as exc:
        return str(exc)
    return None


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


def render(question: Question) -> str:
    """The English surface form of a question."""
    if isinstance(question, AttrQ):
        if question.attr == "color":
            return "What color is %s?" % question.desc.render()
        if question.attr == "size":
            return "How big is %s?" % question.desc.render()
        if question.attr == "kind":
            return "What shape is %s?" % question.desc.render()
        raise QuestionError("unknown attribute %r" % question.attr)

    if isinstance(question, RelQ):
        if question.rel.name == "clear":
            return "Is %s clear?" % question.desc.render()
        if question.rel.name == "supported":
            return "Is %s supported?" % question.desc.render()
        tails = {
            "on_table": "on the table",
            "on": "on %s" % (question.rel.target.render() if question.rel.target else ""),
        }
        if question.rel.name not in tails:
            raise QuestionError("unknown relation %r" % question.rel.name)
        return "Is %s %s?" % (question.desc.render(), tails[question.rel.name])

    if isinstance(question, CountQ):
        return "How many %s are %s?" % (
            question.desc.render_bare_plural(),
            question.rel.render(),
        )

    if isinstance(question, ExistsQ):
        return "Is there %s %s?" % (
            _indefinite(question.desc).render(),
            question.rel.render(),
        )

    if isinstance(question, AllQ):
        return "Are all %s %s?" % (
            question.desc.render_bare_plural(),
            question.rel.render(),
        )

    raise QuestionError("unknown question type %r" % type(question).__name__)


def _indefinite(desc: Desc) -> Desc:
    """The same description, but with the indefinite article."""
    return Desc(
        quant="a",
        color=desc.color,
        size=desc.size,
        kind=desc.kind,
        rels=desc.rels,
    )


# --------------------------------------------------------------------------
# JSON codec — the question-bank format
# --------------------------------------------------------------------------


def rel_to_json(rel: Rel) -> Dict[str, object]:
    out: Dict[str, object] = {"name": rel.name}
    if rel.target is not None:
        out["target"] = desc_to_json(rel.target)
    return out


def rel_from_json(data: Dict[str, object]) -> Rel:
    target = data.get("target")
    return Rel(
        name=str(data["name"]),
        target=desc_from_json(target) if target else None,  # type: ignore[arg-type]
    )


def desc_to_json(desc: Desc) -> Dict[str, object]:
    out: Dict[str, object] = {"quant": desc.quant}
    for key in ("color", "size", "kind"):
        value = getattr(desc, key)
        if value:
            out[key] = value
    if desc.rels:
        out["rels"] = [rel_to_json(r) for r in desc.rels]
    return out


def desc_from_json(data: Dict[str, object]) -> Desc:
    return Desc(
        quant=str(data.get("quant", "the")),
        color=_opt_str(data.get("color")),
        size=_opt_str(data.get("size")),
        kind=_opt_str(data.get("kind")),
        rels=tuple(rel_from_json(r) for r in (data.get("rels") or [])),  # type: ignore[arg-type]
    )


def _opt_str(value: object) -> Optional[str]:
    return None if value is None else str(value)


def question_to_json(question: Question) -> Dict[str, object]:
    if isinstance(question, AttrQ):
        return {"type": "attr", "desc": desc_to_json(question.desc), "attr": question.attr}
    if isinstance(question, RelQ):
        return {"type": "rel", "desc": desc_to_json(question.desc), "rel": rel_to_json(question.rel)}
    if isinstance(question, CountQ):
        return {"type": "count", "desc": desc_to_json(question.desc), "rel": rel_to_json(question.rel)}
    if isinstance(question, ExistsQ):
        return {"type": "exists", "desc": desc_to_json(question.desc), "rel": rel_to_json(question.rel)}
    if isinstance(question, AllQ):
        return {"type": "all", "desc": desc_to_json(question.desc), "rel": rel_to_json(question.rel)}
    raise QuestionError("unknown question type %r" % type(question).__name__)


def question_from_json(data: Dict[str, object]) -> Question:
    kind = str(data["type"])
    desc = desc_from_json(data["desc"])  # type: ignore[arg-type]
    if kind == "attr":
        return AttrQ(desc, str(data["attr"]))
    rel = rel_from_json(data["rel"])  # type: ignore[arg-type]
    if kind == "rel":
        return RelQ(desc, rel)
    if kind == "count":
        return CountQ(desc, rel)
    if kind == "exists":
        return ExistsQ(desc, rel)
    if kind == "all":
        return AllQ(desc, rel)
    raise QuestionError("unknown question type %r" % kind)


def map_desc(question: Question, fn) -> Question:
    """Rebuild ``question`` with ``fn`` applied to every description in it.

    Used by testee variants that read descriptions differently from the
    reference implementation (a testee has to produce it from the wording).
    """

    def go(desc: Desc) -> Desc:
        rebuilt = Desc(
            quant=desc.quant,
            color=desc.color,
            size=desc.size,
            kind=desc.kind,
            rels=tuple(
                Rel(r.name, go(r.target) if r.target is not None else None)
                for r in desc.rels
            ),
        )
        return fn(rebuilt)

    if isinstance(question, AttrQ):
        return AttrQ(go(question.desc), question.attr)
    if isinstance(question, RelQ):
        return RelQ(go(question.desc), _map_rel(question.rel, go))
    if isinstance(question, CountQ):
        return CountQ(go(question.desc), _map_rel(question.rel, go))
    if isinstance(question, ExistsQ):
        return ExistsQ(go(question.desc), _map_rel(question.rel, go))
    if isinstance(question, AllQ):
        return AllQ(go(question.desc), _map_rel(question.rel, go))
    raise QuestionError("unknown question type %r" % type(question).__name__)


def _map_rel(rel: Rel, go) -> Rel:
    if rel.target is None:
        return rel
    return Rel(rel.name, go(rel.target))
