"""How the env side gets hold of a testee: in-process, or as a subprocess.

The names and the building live in :mod:`shrdlu.testee.registry` (they are about
testees); this module adds what only the host needs — the command line for a
testee that runs as its own program, and the working directory and timeout that
go with it.  ``shrdlu-env``, ``shrdlu-play`` and ``shrdlu-report`` all use it.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, List, Optional, Tuple

from .. import transport
from ..testee.registry import (build, describe, is_name, load_class,  # noqa: F401
                               names, needs_picture)

#: The root of the checkout (or the installation), used as the working directory
#: when an external testee command is launched, so that ``shrdlu`` is importable.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: How long a subprocess testee gets per reply when the program has no option of
#: its own (``shrdlu-play`` and ``shrdlu-report`` run named implementations
#: in-process and only need this for a literal command line).
DEFAULT_TIMEOUT = 10.0


def command_line(spec: str) -> List[str]:
    """The subprocess command line for ``spec``.

    ``spec`` is either one of :func:`names` — launched with this interpreter and
    ``shrdlu.testee.cli.testee_main`` — or a literal command line to split.
    """
    if is_name(spec):
        return [sys.executable, "-m", "shrdlu.testee.cli.testee_main", "--impl", spec]
    return spec.split()


def as_testee(
    spec: str,
    model: Optional[str] = None,
    url: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Tuple[object, Callable[[], Optional[str]]]:
    """``(testee, close)`` for a program that prefers to run a name in-process.

    A known name is built here (so a viewer can also show things only an
    in-process object has, such as its prompt history); anything else is a
    command line and is launched as a subprocess.  ``close`` returns whatever
    the testee wrote to stderr, or ``None``.
    """
    if is_name(spec):
        return build(spec, model=model, url=url), (lambda: None)
    player = transport.SubprocessTestee(
        command_line(spec), timeout=timeout, cwd=PROJECT_ROOT
    )
    return player, player.close
