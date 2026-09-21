"""Explicit command capture, exact private logs, bounded diagnostic previews."""

import collections
import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path

from .common import private_dir


def run(store, argv, timeout=120, preview_chars=4000):
    if not argv or not 0 < timeout <= 3600 or not 200 <= preview_chars <= 16000:
        raise ValueError("Provide a command, a timeout up to 3600s and a preview of 200–16000 characters")
    directory = private_dir(store.directory / "logs")
    fd, filename = tempfile.mkstemp(prefix="command-", suffix=".log", dir=directory)
    timed_out = False
    with os.fdopen(fd, "wb") as stream:
        process = subprocess.Popen(argv, cwd=store.root, stdout=stream, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            timed_out = isinstance(exc, subprocess.TimeoutExpired)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            code = 124 if timed_out else 130
    code = code if code >= 0 else 128 - code
    path = Path(filename)
    head, tail, errors = [], collections.deque(maxlen=8), []
    # Inspect bounded head/tail windows, not gigabytes of a noisy command's log.
    with path.open("rb") as stream:
        first = stream.read(65536)
        stream.seek(max(65536, path.stat().st_size - 65536))
        last = stream.read(65536)
        for chunk in (first + last).splitlines(keepends=True):
            line = chunk.decode("utf-8", errors="replace")[:500]
            if len(head) < 4:
                head.append(line)
            if re.search(r"error|fail|traceback|exception|fatal|ошиб|не пройден", line, re.I) and len(errors) < 12:
                errors.append(line)
            tail.append(line)
    available = preview_chars - 40
    head_budget, diagnostic_budget = available // 5, available * 2 // 5
    tail_budget = available - head_budget - diagnostic_budget
    preview = ("HEAD\n" + "".join(head)[:head_budget] + "\nDIAGNOSTIC SAMPLE\n"
               + "".join(errors)[:diagnostic_budget] + "\nTAIL\n" + "".join(tail)[-tail_budget:])
    return {"exit_code": code, "timed_out": timed_out, "log": filename,
            "bytes": path.stat().st_size, "preview": preview,
            "notice": "Bounded heuristic sample, not a complete error summary. "
                      "Full combined stdout/stderr is in the local log; inspect it when needed."}
