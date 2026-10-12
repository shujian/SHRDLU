"""One place for the defaults: the ``shrdlu.ini`` file.

Every program has options, but almost every run wants the same handful of
values.  Those live in a small INI file, so a command line can stay short::

    python3 -m shrdlu.env.cli.env_main --seed 3      # everything else from the file

The file is looked for by walking up from the current directory; the
environment variable ``SHRDLU_CONFIG`` names one explicitly.  With no file at
all the built-in defaults below apply, so a checkout works before anybody
writes one.

Two kinds of section:

* ``[shrdlu]`` — shared defaults, read by every program that does not declare
  the key itself;
* ``[shrdlu-env]`` … — a program's own keys, which win over the shared section.
  A program that declares a key owns it outright: the shared value is then
  ignored, so an empty value there really means "not set" (``shrdlu-exam``
  writes ten questions, not the shared zero).

Command-line options still win over both: the file says what a plain run does,
a flag says what this run does differently.

Inspect or refresh it with::

    python3 -m shrdlu.settings                       # what is in effect, and from where
    python3 -m shrdlu.settings --write shrdlu.ini    # a commented file at the defaults
"""

from __future__ import annotations

import argparse
import configparser
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
#: The root of the checkout (or of an installation), used as a fallback place
#: to look for the file and as the working directory for external testees.
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)

#: The file looked for, and the name ``--write`` uses by default.
CONFIG_NAME = "shrdlu.ini"

#: The section every program reads first.
SHARED = "shrdlu"

#: Which section a program reads second (its own overrides).
PROGRAM_SECTIONS = {
    "env": "shrdlu-env",
    "play": "shrdlu-play",
    "report": "shrdlu-report",
    "render": "shrdlu-render",
    "scene": "shrdlu-scene",
    "exam": "shrdlu-exam",
    "testee": "shrdlu-testee",
}

#: Where an explicit file may be named.
ENV_VAR = "SHRDLU_CONFIG"

#: ``(key, kind, default, help)``.  ``default`` may be ``None``, which means
#: "not set": the program then uses whatever its own fallback is (an empty
#: ``steps`` lets the exam author choose, an empty ``scenario`` means "make one
#: from the seed", and so on).
Key = Tuple[str, str, Any, str]


SHARED_KEYS: Tuple[Key, ...] = (
    ("scenario", "str", None,
     "默认场景（留空 = first-version）；只因 seed 而现场生成整卷时，这一项留空"),
    ("questions", "int", 0,
     "0 = 用场景自带的题库；大于 0 = 现场重出这么多道题"),
    ("seed", "int", None,
     "与 questions 同用时是出题种子；单独给就现场造一整份考卷"),
    ("shapes", "str", "attr,rel,count,exists,all",
     "现场出题时允许的题型"),
    ("testee", "str", "example",
     "已知实现名（example）、模块:类，或一条命令"),
    ("observe", "str", "state",
     "测试开始时给什么：state（符号）或 image（一张图）"),
    ("timeout", "float", 10.0,
     "等被测者每条回复的秒数"),
    ("record", "str", None,
     "把测试记录写成 JSON 的路径；留空 = 不写"),
    ("quiet", "bool", False,
     "只打印结论"),
)

#: Per program: the keys it reads, plus the defaults that differ from the
#: shared ones.  The first entry is always used when the key is absent.
PROGRAM_KEYS: Dict[str, Tuple[Key, ...]] = {
    "env": (),
    "play": (
        ("pause", "bool", True, "每步停下来；关掉就一口气跑完"),
    ),
    "report": (
        ("out", "str", "report.html", "报告写到哪个文件"),
        ("open", "bool", False, "写好之后用浏览器打开"),
    ),
    "render": (
        ("scenario", "str", None, "画这个场景；留空 = 按 seed 现场生成"),
        ("stage", "str", "initial", "渲染哪个状态：initial / final / both"),
        ("scale", "float", 2.0, "PNG 的像素倍率"),
        ("labels", "bool", True, "是否画 id 标签"),
        ("out_dir", "str", None, "批量输出目录（每个状态一张 SVG）"),
    ),
    "scene": (
        ("level", "int", 1, "场景等级（目前只有 1）"),
        ("out_dir", "str", None, "批量输出目录"),
    ),
    "exam": (
        ("scene", "str", None, "给这个场景出题；留空 = 按 seed 现场造一个"),
        ("seed", "int", 0, "造场景与出题用的种子"),
        ("questions", "int", 10, "写多少道题"),
        ("steps", "int", None, "指令条数；留空 = 出题器自选（3 或 4）"),
        ("illegal", "int", 1, "其中几条是陷阱指令"),
        ("reasoning_ratio", "float", 0.5, "「必须推演」的题所占比例下限"),
        ("out", "str", None, "写出的考卷路径"),
    ),
    "testee": (
        ("impl", "str", "example", "跑哪个实现"),
    ),
}


class SettingsError(Exception):
    """Raised when a settings file cannot be read or holds a bad value."""


def _spec(program: str) -> Tuple[Key, ...]:
    """Every key ``program`` reads: its own first, then the shared ones it does
    not declare itself (a declared key is owned outright)."""
    if program not in PROGRAM_KEYS:
        raise SettingsError("unknown program %r; choose from: %s"
                            % (program, ", ".join(sorted(PROGRAM_KEYS))))
    own = PROGRAM_KEYS[program]
    known = {key for key, _, _, _ in own}
    return own + tuple(item for item in SHARED_KEYS if item[0] not in known)


def _section_keys(program: str) -> Tuple[Key, ...]:
    """The keys written into that program's own section."""
    return PROGRAM_KEYS[program]


def find(path: Optional[str] = None, start: Optional[str] = None) -> Optional[str]:
    """The settings file to read, or ``None`` when there is none.

    Order: ``path``, then ``SHRDLU_CONFIG``, then ``shrdlu.ini`` in the current
    directory or any parent, then next to the package.  A file that is named
    but missing is an error, not a silent fallback.
    """
    if path:
        if not os.path.isfile(path):
            raise SettingsError("no such settings file: %s" % path)
        return path
    named = os.environ.get(ENV_VAR)
    if named:
        if not os.path.isfile(named):
            raise SettingsError("%s points at a missing file: %s" % (ENV_VAR, named))
        return named

    here = os.path.abspath(start or os.getcwd())
    while True:
        candidate = os.path.join(here, CONFIG_NAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent

    beside = os.path.join(PROJECT_ROOT, CONFIG_NAME)
    return beside if os.path.isfile(beside) else None


def _read(path: Optional[str]) -> Dict[str, Dict[str, str]]:
    if path is None:
        return {}
    # inline comments are what make the shipped file readable
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        raise SettingsError("cannot read %s: %s" % (path, exc)) from exc
    return {name: dict(parser.items(name)) for name in parser.sections()}


def _coerce(path: str, section: str, key: str, kind: str, raw: str) -> Any:
    text = str(raw).strip()
    if text == "":
        return None                       # "not set": the program's own fallback
    try:
        if kind == "int":
            return int(text)
        if kind == "float":
            return float(text)
        if kind == "bool":
            lowered = text.lower()
            if lowered in ("yes", "true", "1", "on"):
                return True
            if lowered in ("no", "false", "0", "off"):
                return False
            raise ValueError("expected yes or no")
        return text
    except ValueError as exc:
        raise SettingsError("%s: [%s] %s = %r is not a valid %s (%s)"
                            % (path, section, key, text, kind, exc)) from exc


class Settings:
    """The values one program runs with, after file and defaults are merged."""

    def __init__(self, program: str, values: Dict[str, Any],
                 source: Optional[str] = None) -> None:
        self.program = program
        self.values = values
        self.source = source

    def __getitem__(self, key: str) -> Any:
        try:
            return self.values[key]
        except KeyError:
            raise SettingsError("program %r has no setting %r" % (self.program, key))

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.values)

    def source_text(self) -> str:
        return self.source or "(内置默认值)"

    def describe(self) -> str:
        lines = ["%s: %s" % (self.program, self.source_text())]
        for key, kind, _, help_text in _spec(self.program):
            value = self.values[key]
            shown = "（未设）" if value is None else (
                "是" if value is True else "否" if value is False else str(value))
            lines.append("  %-16s %-10s %s" % (key, shown, help_text))
        return "\n".join(lines)


def load(program: str, path: Optional[str] = None,
         start: Optional[str] = None) -> Settings:
    """The settings ``program`` should run with.

    Raises :class:`SettingsError` for an unreadable file, an unknown key in a
    section this program reads, or a value of the wrong kind.
    """
    spec = _spec(program)
    found = find(path, start=start)
    raw = _read(found)
    shared = raw.get(SHARED, {})
    own_section = PROGRAM_SECTIONS[program]
    own = raw.get(own_section, {})

    if found is not None:
        known = {key for key, _, _, _ in spec}
        stray = sorted(set(own) - known)
        if stray:
            raise SettingsError("%s: [%s] has key(s) this program does not read: %s"
                                % (found, own_section, ", ".join(stray)))
        shared_known = {key for key, _, _, _ in SHARED_KEYS}
        stray_shared = sorted(set(shared) - shared_known)
        if stray_shared:
            raise SettingsError("%s: [%s] has unknown key(s): %s (a program's own keys "
                                "belong in its own section, e.g. [%s])"
                                % (found, SHARED, ", ".join(stray_shared),
                                   PROGRAM_SECTIONS["render"]))

    declared = {key for key, _, _, _ in PROGRAM_KEYS[program]}
    values: Dict[str, Any] = {}
    for key, kind, default, _ in spec:
        if key in own:
            values[key] = _coerce(found, own_section, key, kind, own[key])
        elif key in declared:
            # owned by this program: the shared section has no say
            values[key] = default
        elif key in shared:
            values[key] = _coerce(found, SHARED, key, kind, shared[key])
        else:
            values[key] = default
    return Settings(program, values, source=found)


# --------------------------------------------------------------------------
# Writing and printing the file
# --------------------------------------------------------------------------


def _render_key(key: str, kind: str, default: Any, help_text: str) -> str:
    if default is None:
        shown = ""
    elif isinstance(default, bool):
        shown = "yes" if default else "no"
    else:
        shown = str(default)
    return "%-18s = %-32s # %s" % (key, shown, help_text)


def default_text() -> str:
    """The commented file with every key at its default."""
    out: List[str] = [
        "# shrdlu 的默认值。命令行参数会覆盖这里；本文件改坏了会直接报错。",
        "#",
        "# 查找顺序：SHRDLU_CONFIG 指的文件 → 当前目录及其各级父目录的 shrdlu.ini",
        "#          → 项目根目录的 shrdlu.ini → 内置默认值。",
        "# 公共段 [shrdlu] 所有程序都读；某个程序的段只覆盖它自己不同的键。",
        "# 查看当前生效的值：python3 -m shrdlu.settings [--program env]",
        "",
        "[%s]" % SHARED,
    ]
    for key, kind, default, help_text in SHARED_KEYS:
        out.append(_render_key(key, kind, default, help_text))

    for program in ("play", "report", "render", "scene", "exam", "testee"):
        section = PROGRAM_SECTIONS[program]
        out.append("")
        out.append("[%s]" % section)
        for key, kind, default, help_text in _section_keys(program):
            out.append(_render_key(key, kind, default, help_text))

    out.append("")
    out.append("[%s]" % PROGRAM_SECTIONS["env"])
    out.append("# 测试者没有自己的键：它全部读上表的公共段。")
    out.append("")
    return "\n".join(out)


def write_default(path: str, force: bool = False) -> str:
    """Write :func:`default_text` to ``path`` (unless it exists)."""
    if os.path.exists(path) and not force:
        raise SettingsError("%s already exists (use --force to overwrite)" % path)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(default_text())
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="shrdlu-settings",
        description="Show, or write out, the settings every program reads.",
    )
    parser.add_argument("--program", "-p", default=None,
                        help="show one program's effective values (default: all)")
    parser.add_argument("--write", default=None, metavar="PATH",
                        help="write a commented file at the defaults")
    parser.add_argument("--force", action="store_true",
                        help="overwrite when --write names an existing file")
    args = parser.parse_args(argv)

    if args.write:
        try:
            path = write_default(args.write, force=args.force)
        except SettingsError as exc:
            print("error: %s" % exc, file=sys.stderr)
            return 2
        print("written %s" % path)
        return 0

    programs = [args.program] if args.program else list(PROGRAM_KEYS)
    try:
        blocks = [load(program).describe() for program in programs]
    except SettingsError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print("\n".join(blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
