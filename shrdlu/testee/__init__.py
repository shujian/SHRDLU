"""testee：被测者一侧的接口、参考实现与校准用变体。

接口的约定见 ``README.md`` §6，Python 绑定是 :mod:`shrdlu.testee.api`::

    from shrdlu.testee import Action, Observation, Refuse, Testee
"""

from .api import Action, Observation, Refuse, Testee  # noqa: F401

__all__ = ["Action", "Observation", "Refuse", "Testee"]
