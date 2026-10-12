"""The text protocol between the env program and the testee program.

Everything that crosses the boundary is **one JSON object per line**.  Even
when both programs run in the same process (which is how the tests and early
development work), the messages are encoded to text and decoded again, so the
boundary is real and swapping in two OS processes later changes only the
transport.

env -> testee
    {"type": "observe",  "state": {...}}          once, at the start; no reply
    {"type": "observe",  "image": {...}}          ...or a picture of it instead
    {"type": "command",  "text": "Pick up the ..."}
    {"type": "question", "text": "Is the ... clear?"}

testee -> env
    {"type": "action", "op": "put_on", "args": ["a", "b"]}
    {"type": "refuse", "reason": "..."}
    {"type": "answer", "text": "yes"}

``observe`` is fire-and-forget: the testee reads it and replies with nothing.
Every other message is a request that must be answered.

It carries either the state, or a picture of it, or both — but never more than
one look, and never a second one later.  Which of the two it carries is the
whole question about a testee that is supposed to *see*: if ``state`` is on the
wire, the picture is decoration.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Dict, List, Optional, Sequence


class ProtocolError(Exception):
    """Raised when a message is not a well-formed protocol message."""


def encode(kind: str, **fields: object) -> str:
    """Build one protocol line."""
    payload: Dict[str, object] = {"type": kind}
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False)


def decode(line: str) -> Dict[str, object]:
    """Parse one protocol line, checking that it is a message we know."""
    if line is None:
        raise ProtocolError("empty message")
    text = str(line).strip()
    if not text:
        raise ProtocolError("empty message")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProtocolError("not valid JSON: %s" % exc)
    if not isinstance(data, dict):
        raise ProtocolError("message must be a JSON object")
    kind = data.get("type")
    if kind not in ("observe", "command", "question", "action", "refuse", "answer"):
        raise ProtocolError("unknown message type %r" % (kind,))
    return data


# -- env-side constructors -------------------------------------------------


def observe(state: Optional[Dict[str, object]] = None,
            image: Optional[bytes] = None, image_format: str = "png",
            scale: float = 2.0) -> str:
    """The one and only look at the world.

    Either field may be omitted, and exactly what is sent is a decision made by
    the env, not a convenience: a testee that is meant to *see* must not
    receive ``state`` at all, or nothing about its perception is being tested.
    """
    fields: Dict[str, object] = {}
    if state is not None:
        fields["state"] = state
    if image is not None:
        fields["image"] = {
            "format": image_format,
            "scale": scale,
            "data": base64.b64encode(image).decode("ascii"),
        }
    if not fields:
        raise ProtocolError("an observation must carry a state, an image, or both")
    return encode("observe", **fields)


def observation_image(msg: Dict[str, object]) -> Optional[bytes]:
    """The picture in an ``observe`` message, decoded.  ``None`` if there is none."""
    image = msg.get("image")
    if not isinstance(image, dict):
        return None
    data = image.get("data")
    if not isinstance(data, str):
        raise ProtocolError("observation image has no data")
    try:
        return base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProtocolError("observation image is not valid base64: %s" % exc) from exc


def command(text: str) -> str:
    return encode("command", text=text)


def question(text: str) -> str:
    return encode("question", text=text)


# -- testee-side constructors ----------------------------------------------


def action(op: str, args: Sequence[str]) -> str:
    return encode("action", op=op, args=list(args))


def refuse(reason: str = "") -> str:
    return encode("refuse", reason=reason)


def answer(text: str) -> str:
    return encode("answer", text=text)


# -- field accessors -------------------------------------------------------


def message_text(message: Dict[str, object]) -> str:
    return str(message.get("text", ""))


def message_op(message: Dict[str, object]) -> str:
    return str(message.get("op", ""))


def message_args(message: Dict[str, object]) -> List[str]:
    args = message.get("args") or []
    if not isinstance(args, (list, tuple)):
        raise ProtocolError("args must be a list")
    return [str(a) for a in args]
