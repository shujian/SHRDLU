#!/bin/sh
# Everything that has to pass before this is worth shipping.
#
# The test suite runs against the source checkout, which is not the same thing
# as running an installed package: the scenario data has to be inside the wheel,
# or a match run from an installed package finds no scenario.  That is exactly
# the bug this script was written after, so the last step unpacks the wheel
# somewhere else and plays a match there.
#
#     tools/check.sh
#
# No CI service is configured; this is the part of it that does not depend on
# one.  Run it from the project root.

set -eu

PYTHON="${PYTHON:-python3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cd "$ROOT"
echo "== 语法 =="
"$PYTHON" -m compileall -q shrdlu tests
echo "ok"

echo
echo "== 测试 =="
"$PYTHON" -m unittest discover -s tests

echo
echo "== 打包 =="
"$PYTHON" -m pip wheel --no-deps --no-build-isolation -w "$WORK/wheels" . >/dev/null
WHEEL="$(ls "$WORK"/wheels/*.whl)"
echo "built $(basename "$WHEEL")"

echo
echo "== 装到别处跑一局 =="
mkdir -p "$WORK/site"
(cd "$WORK/site" && "$PYTHON" -m zipfile -e "$WHEEL" .)
if [ ! -f "$WORK/site/shrdlu/scenarios/first-version.json" ]; then
    echo "!! the wheel does not carry scenarios/first-version.json" >&2
    exit 1
fi
# Run from a directory that is not the project, with only the unpacked wheel on
# the path, so nothing but the wheel's own scenario data can be reached.
# 判定为"不理解"时退出码是 1，这正是自带最小示例的预期结果；只有更大的退出码
# （配置或场景出错）才算这一步失败。
code=0
(cd "$WORK" && PYTHONPATH="$WORK/site" "$PYTHON" -m shrdlu.env.cli.env_main \
    --scenario first-version --questions 10 --seed 3 --quiet) || code=$?
if [ "$code" -gt 1 ]; then
    echo "!! the installed package cannot run a match (exit $code)" >&2
    exit 1
fi

echo
echo "== 不带 shrdlu.ini 也能跑（内置默认值） =="
# The wheel carries no settings file; the built-in defaults have to be enough.
code=0
(cd "$WORK" && PYTHONPATH="$WORK/site" "$PYTHON" -m shrdlu.env.cli.env_main --quiet) || code=$?
if [ "$code" -gt 1 ]; then
    echo "!! the installed package cannot run without a settings file (exit $code)" >&2
    exit 1
fi
(cd "$WORK" && PYTHONPATH="$WORK/site" "$PYTHON" -m shrdlu.settings --program env \
    | head -1)

echo
echo "全部通过。"
