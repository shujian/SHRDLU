"""Which testee implementation to run, by name.

本仓库只带一个最小示例（:mod:`shrdlu.testee.example`）；真正的实现由使用者自己写，
用 ``模块:类`` 指定即可，四个程序（``shrdlu-testee`` / ``shrdlu-env`` /
``shrdlu-play`` / ``shrdlu-report``）都读这一张名册。
"""

from __future__ import annotations

import importlib
from typing import List, Optional

from . import example

#: 内置实现只有一个：最小示例。
BUILT_IN = ("example",)


def names() -> List[str]:
    """Every implementation name, in the order they should be offered."""
    return list(BUILT_IN)


def is_name(value: str) -> bool:
    """True when ``value`` names a built-in implementation or a ``module:Class``.

    Anything else is taken to be a command line.
    """
    return value in names() or ":" in value


def needs_picture(spec: str) -> bool:
    """True when ``spec`` (a name) must be shown a picture and nothing else.

    本仓库不带看图实现，因此恒为 False；自带实现需要图片时，自己用
    ``--observe image`` 启动即可。
    """
    return False


def load_class(spec: str):
    """The class named by ``"module:Class"``."""
    module_name, _, class_name = spec.partition(":")
    if not module_name or not class_name:
        raise LookupError("%r is not a module:Class reference" % spec)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise LookupError("cannot import %r (for %r): %s" % (module_name, spec, exc)) from exc
    try:
        return getattr(module, class_name)
    except AttributeError as exc:
        raise LookupError("%s has no %r" % (module_name, class_name)) from exc


def build(name: str, model: Optional[str] = None, url: Optional[str] = None):
    """The implementation called ``name``, ready to be handed messages.

    ``name`` is ``example`` or a ``module:Class`` of your own; ``model`` and
    ``url`` are unused here and kept so callers can pass their options through.
    """
    if ":" in name:
        return load_class(name)()
    if name == "example":
        return example.ExampleTestee()
    raise LookupError(
        "unknown testee %r; choose from: %s" % (name, ", ".join(sorted(names())))
    )


def describe(name: str) -> str:
    """A one-line description, for ``--list`` and for error messages."""
    if ":" in name:
        return "a testee class loaded from %s" % name
    if name == "example":
        return "只回拒绝的最小示例：用来打通链路"
    return "unknown"
