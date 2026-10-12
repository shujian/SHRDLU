"""The testee-side interface: what a testee implements, and how it meets the wire.

``README.md`` §6 states the framework both sides follow: the two sides exchange
one JSON object per line, and a testee answers three things — the one
observation it is shown, the questions it is asked, and the instructions it is
given.  ``docs/设计协议.md`` §5 is the field-level spec of those messages.
This module is the same contract in Python::

    from shrdlu.testee.api import Action, Observation, Refuse, Testee

    class MyTestee(Testee):
        def observe(self, observation: Observation) -> None:
            ...                                   # 唯一一次观察，没有回复

        def question(self, text: str):
            return "yes"                          # 或 Refuse("...")

        def command(self, text: str):
            return Action("put_on", ("a", "b"))   # 或 Refuse("...")

跑起来（进程内或独立进程都行）::

    python3 -m shrdlu.testee.cli.testee_main --impl my_module:MyTestee
    python3 -m shrdlu.env.cli.env_main    --testee my_module:MyTestee
    python3 -m shrdlu.env.cli.play_main   --testee my_module:MyTestee

:meth:`Testee.handle` 是这套接口与线上协议的绑定：它解码一行消息，调用对应的入口，
再把返回值编码成一行回复。其它语言不必依赖本模块，按同一套入口直接实现线上协议即可。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union

from .. import protocol


@dataclass(frozen=True)
class Observation:
    """被测者得到的唯一一次世界信息：符号状态、一张图，二者之一。"""

    state: Optional[Dict[str, object]] = None
    image: Optional[bytes] = None
    image_format: str = "png"

    @property
    def is_empty(self) -> bool:
        return self.state is None and self.image is None


@dataclass(frozen=True)
class Action:
    """一条操作调用：对指令的回答。"""

    op: str
    args: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Refuse:
    """拒绝，附带给测试者的理由。"""

    reason: str = ""


#: 指令的回答：操作调用，或拒绝
Reply = Union[Action, Refuse]

#: 问句的回答：封闭式答句、拒绝，或什么也不回（沉默按没有回复计）
Answer = Union[str, Refuse, None]


class Testee(abc.ABC):
    """三个入口；:meth:`handle` 把它们接到线上协议上。"""

    @abc.abstractmethod
    def observe(self, observation: Observation) -> None:
        """接受这一次观察，建立自己那份世界认识。没有返回值，不回复。"""

    @abc.abstractmethod
    def question(self, text: str) -> Answer:
        """回答一个问句：封闭式答句，或 :class:`Refuse`。"""

    @abc.abstractmethod
    def command(self, text: str) -> Reply:
        """回答一条指令：:class:`Action`，或 :class:`Refuse`。"""

    # -- 与线上协议的绑定 --------------------------------------------------
    def handle(self, message: str) -> str:
        """吃一行协议消息，吐一行回复；由 ``transport.serve`` 循环调用。"""
        msg = protocol.decode(message)
        kind = msg.get("type")

        if kind == "observe":
            self.observe(_observation(msg))
            self._observed = True
            return ""

        if not getattr(self, "_observed", False):
            return protocol.refuse("I have not seen the world yet")

        if kind == "command":
            return _encode_reply(self.command(protocol.message_text(msg)))
        if kind == "question":
            return _encode_answer(self.question(protocol.message_text(msg)))
        return protocol.refuse("I do not understand that message")


def _observation(message: Dict[str, object]) -> Observation:
    """把 ``observe`` 消息的载荷读成 :class:`Observation`。"""
    state = message.get("state")
    if state is not None and not isinstance(state, dict):
        raise protocol.ProtocolError("the observation's state is not an object")
    raw = message.get("image")
    image_format = "png"
    if isinstance(raw, dict) and isinstance(raw.get("format"), str):
        image_format = str(raw["format"])
    return Observation(state=state, image=protocol.observation_image(message),
                       image_format=image_format)


def _encode_reply(reply: Reply) -> str:
    if isinstance(reply, Action):
        return protocol.action(reply.op, list(reply.args))
    if isinstance(reply, Refuse):
        return protocol.refuse(reply.reason)
    raise TypeError("一条指令只能用 Action 或 Refuse 回答，收到 %r" % (reply,))


def _encode_answer(answer: Answer) -> str:
    if answer is None:
        return ""                       # 沉默：记为没有回复
    if isinstance(answer, Refuse):
        return protocol.refuse(answer.reason)
    return protocol.answer(str(answer))
