"""Fail-open optional compact-plus bridge with activation and auxiliary usage records."""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from context_economy.meter import session_read

HOOKS = {"precompact-transcript-backup.sh", "precompact-state-summary.sh", "compaction-recovery.sh",
         "sessionstart-compaction-recovery.sh", "sessionstart-export-session-id.sh",
         "userpromptsubmit-compaction-recovery.sh", "userpromptsubmit-compact-plus-reminder.sh"}


def journal(home, value):
    folder = home / "economy-metrics"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / "compaction.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as stream:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(dict(value, timestamp=time.time())) + "\n")


def prior_counter(home, session):
    path = home / "economy-metrics/compaction.jsonl"
    if not path.exists():
        return 0
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 1024 * 1024))
        lines = stream.read().splitlines()
    for line in reversed(lines):
        try:
            row = json.loads(line)
            if row.get("session") == session and row.get("status") == "attempted":
                return row["source_counter"]
        except (ValueError, KeyError):
            continue
    return 0


def eligible(home, event):
    source = event.get("transcript_path") or event.get("transcriptPath")
    if not source:
        return None, "missing exact transcript"
    path = Path(source).absolute()
    if not path.is_relative_to(home / "sessions"):
        return None, "transcript is outside this CODEX_HOME/sessions"
    if path.stat().st_size < int(os.environ.get("COMPACT_PLUS_MIN_TRANSCRIPT_BYTES", "65536")):
        return None, "short session"
    data = session_read(path)
    if data["counter_reset"]:
        return None, "source counter reset"
    tokens = data["total"]
    if not all(k in tokens for k in ("input_tokens", "cached_input_tokens", "output_tokens")):
        return None, "source usage unknown"
    counter = tokens["input_tokens"] - tokens["cached_input_tokens"] + tokens["output_tokens"]
    session = hashlib.sha256(str(path).encode()).hexdigest()[:24]
    delta = counter - prior_counter(home, session)
    threshold = int(os.environ.get("COMPACT_PLUS_MIN_UNCACHED_TOKENS", "40000"))
    if threshold < 1 or delta < threshold:
        return None, "below activation threshold or counter reset"
    return {"session": session, "source_counter": counter}, None


def backend():
    """Called by compact-plus only after eligibility. No raw model stream is persisted."""
    home = Path(os.environ["CODEX_HOME"]).absolute()
    started = time.monotonic()
    usage = None
    status = "failed"
    returncode = 1
    launches = 0
    try:
        prompt = sys.stdin.read(256 * 1024 + 1)
        if len(prompt) > 256 * 1024:
            raise ValueError("Summary prompt too large")
        with tempfile.TemporaryDirectory(prefix="economy-summary-") as directory:
            output = Path(directory) / "summary.txt"
            events = Path(directory) / "events.jsonl"
            # Isolate auxiliary configuration/auth-free settings; Codex retains its
            # normal authentication resolution, but cannot inherit recursive hooks.
            argv = ["codex", "exec", "--ignore-user-config", "--ephemeral", "--json",
                    "--model", "gpt-5.6-luna", "-c", 'model_reasoning_effort="low"',
                    "--sandbox", "read-only", "--skip-git-repo-check", "--output-last-message", str(output), "-"]
            with events.open("w+") as stream:
                launches = 1
                result = subprocess.run(argv, input=os.environ.get("SYSTEM_PROMPT", "") + "\n\n" + prompt,
                                        text=True, stdout=stream, stderr=subprocess.DEVNULL, timeout=40)
                stream.seek(0)
                for line in stream:
                    try:
                        row = json.loads(line)
                        if row.get("type") == "turn.completed":
                            usage = row.get("usage")
                    except ValueError:
                        continue
            returncode = result.returncode
            if returncode == 0 and output.exists():
                text = output.read_text()
                if len(text.encode()) > 12000:
                    raise ValueError("Summary exceeds output byte limit")
                print(text, end="")
                status = "completed"
    except (OSError, ValueError, subprocess.SubprocessError):
        returncode = 1
    finally:
        allowed = {k: usage.get(k) if isinstance(usage, dict) else None for k in
                   ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")}
        journal(home, {"status": status, "session": os.environ.get("ECONOMY_COMPACTION_SESSION"),
                       "model": "gpt-5.6-luna", "effort": "low", "model_launches": launches,
                       "actual_codex_tokens": allowed, "api_cost_usd": None,
                       "elapsed_seconds": time.monotonic() - started})
    return returncode


def main():
    if sys.argv[1:] == ["--backend"]:
        return backend()
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).absolute()
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in HOOKS:
        raise ValueError("Unknown compact-plus hook")
    payload = sys.stdin.buffer.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise ValueError("Oversized hook payload")
    root = Path(os.environ.get("COMPACT_PLUS_PLUGIN_ROOT", str(home / "plugins/compact-plus")))
    hook = root / "hooks" / name
    if not hook.is_file():
        journal(home, {"status": "skipped", "reason": "optional compact-plus plugin missing", "model_launches": 0})
        return 0
    env = dict(os.environ, CODEX_HOME=str(home))
    if name == "precompact-state-summary.sh":
        event = json.loads(payload)
        if not isinstance(event, dict):
            raise ValueError("Hook input must be an object")
        state, reason = eligible(home, event)
        if state is None or not shutil.which("codex"):
            journal(home, {"status": "skipped", "reason": reason or "codex missing", "model_launches": 0})
            return 0
        journal(home, dict(state, status="attempted", model_launches=0))
        env.update(ECONOMY_COMPACTION_SESSION=state["session"],
                   COMPACT_PLUS_PRIMARY_BACKEND=shlex.join([sys.executable, str(Path(__file__).resolve()), "--backend"]),
                   COMPACT_PLUS_FALLBACK_BACKEND="", COMPACT_PLUS_MAX_OUTPUT_TOKENS="1200",
                   COMPACT_PLUS_BACKEND_TIMEOUT="45", COMPACT_PLUS_TWO_PASS="0")
    env.update(COMPACT_PLUS_CODEX_WARN_THRESHOLD="65", COMPACT_PLUS_SQUASH_ENABLED="1",
               COMPACT_PLUS_SQUASH_READ_LINES="80", COMPACT_PLUS_SQUASH_BASH_CHARS="800")
    result = subprocess.run(["bash", str(hook), *sys.argv[2:]], input=payload, env=env, timeout=100)
    if result.returncode:
        print("compact-plus-hook: optional hook failed; continuing", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print(f"compact-plus-hook: skipped ({type(exc).__name__}); continuing", file=sys.stderr)
        raise SystemExit(0)
