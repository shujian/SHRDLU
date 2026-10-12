"""Transport: running the testee as a separate program.

The host only ever hands its testee text and gets text back
(:class:`shrdlu.host.Testee`), so making the testee a real OS process is a
transport swap, not a redesign.

Both sides speak **one JSON object per line** (protocol §5.4).  ``observe`` is
fire-and-forget and gets no reply; every other message is a request that must
be answered.

Reading uses the raw file descriptor rather than the buffered stream: mixing
``select`` with Python's buffered reader can report "not ready" while a whole
line is already sitting in the buffer.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import threading
import time
from typing import IO, Callable, List, Optional, Sequence

from . import protocol


class TransportError(Exception):
    """Raised when the testee process cannot be talked to."""


class TesteeTimeout(TransportError):
    """Raised when the testee does not answer in time."""


class _LineReader:
    """Line reader over a raw file descriptor, with a timeout."""

    def __init__(self, stream: IO[bytes]) -> None:
        self.stream = stream
        self.buffer = b""

    def readline(self, timeout: float) -> Optional[str]:
        deadline = time.monotonic() + max(0.0, timeout)
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                ready, _, _ = select.select([self.stream], [], [], remaining)
            except (OSError, ValueError) as exc:  # stream closed
                raise TransportError("cannot read from the testee: %s" % exc)
            if not ready:
                return None
            chunk = os.read(self.stream.fileno(), 65536)
            if not chunk:
                return None
            self.buffer += chunk
        line, _, self.buffer = self.buffer.partition(b"\n")
        return line.decode("utf-8", errors="replace")


class SubprocessTestee:
    """Runs a testee command and speaks the protocol to it."""

    def __init__(
        self,
        argv: Sequence[str],
        timeout: float = 10.0,
        cwd: Optional[str] = None,
    ) -> None:
        self.argv = list(argv)
        self.timeout = timeout
        self.exchanges: List[str] = []
        self._stderr_chunks: List[bytes] = []
        self._stderr_thread: Optional[threading.Thread] = None
        try:
            self.process = subprocess.Popen(
                self.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
            )
        except OSError as exc:
            raise TransportError("cannot start the testee %r: %s" % (self.argv, exc))
        assert self.process.stdin is not None and self.process.stdout is not None
        self.reader = _LineReader(self.process.stdout)
        if self.process.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, name="shrdlu-testee-stderr", daemon=True
            )
            self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        """Continuously drain stderr so the child cannot block on a full pipe."""
        if self.process.stderr is None:
            return
        try:
            while True:
                chunk = self.process.stderr.read(8192)
                if not chunk:
                    return
                self._stderr_chunks.append(chunk)
        except (OSError, ValueError):
            return

    # -- Testee interface --------------------------------------------------
    def handle(self, message: str) -> str:
        self.exchanges.append(message)
        self._write(message)
        if _is_observe(message):
            return ""
        line = self.reader.readline(self.timeout)
        if line is None:
            raise TesteeTimeout(
                "the testee did not answer within %.1fs (exit code %s)"
                % (self.timeout, self.process.poll())
            )
        return line

    def _write(self, message: str) -> None:
        assert self.process.stdin is not None
        try:
            self.process.stdin.write((message + "\n").encode("utf-8"))
            self.process.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise TransportError("the testee closed its input: %s" % exc)

    # -- lifecycle ---------------------------------------------------------
    def close(self, timeout: float = 5.0) -> Optional[str]:
        """Close the pipes, wait for exit, and return any stderr text."""
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=1.0)
        stderr_text = b"".join(self._stderr_chunks).decode("utf-8", errors="replace")
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (ValueError, OSError):
                    pass
        return stderr_text

    def __enter__(self) -> "SubprocessTestee":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def _is_observe(message: str) -> bool:
    try:
        return protocol.decode(message).get("type") == "observe"
    except protocol.ProtocolError:
        return False


# --------------------------------------------------------------------------
# Testee side
# --------------------------------------------------------------------------


def serve(
    testee,
    stdin: IO[bytes] = None,
    stdout: IO[bytes] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
) -> int:
    """Read protocol lines from ``stdin`` and write replies to ``stdout``.

    Returns a process exit code.  A malformed line does not kill the testee:
    it gets a refusal, so a bad host cannot take the testee down either.
    """
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer

    while True:
        raw = stdin.readline()
        if not raw:
            return 0
        message = raw.decode("utf-8", errors="replace").strip()
        if not message:
            continue
        try:
            reply = testee.handle(message)
        except Exception as exc:  # the testee must survive its own bugs
            if on_error is not None:
                on_error(exc)
            try:
                reply = protocol.refuse("internal error: %s" % exc)
            except Exception:
                return 1
        if reply:
            stdout.write((reply + "\n").encode("utf-8"))
            stdout.flush()
