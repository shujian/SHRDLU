"""最小实现：只保证协议链路通，不实现任何理解。

它收下观察，对每个问句答 ``no``，对每条指令回拒绝 —— 判定结果必然是"不理解"，
但双方的消息能对上，足以用来打通链路、或作为自己实现的起点。
"""

from __future__ import annotations

from .api import Observation, Refuse, Testee


class ExampleTestee(Testee):
    """三个入口的最小写法。"""

    def observe(self, observation: Observation) -> None:
        self.state = observation.state          # 也可以只用 observation.image

    def question(self, text: str):
        return "no"                             # 或 Refuse("...")

    def command(self, text: str):
        return Refuse("not implemented yet")    # 或 Action("put_on", ("a", "b"))
