"""Bounded durable foreground jobs; interrupted jobs are never silently retried."""

import argparse
import json
import os
import signal
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .common import digest, encode, private_dir, read_source
from .quality_common import sources

GROUPS = {"index-update": "heavy", "repo-map": "heavy", "quality-verify": "heavy", "relations": "heavy",
          "search": "retrieval", "symbols": "retrieval", "callers": "retrieval", "tests": "retrieval",
          "source-read": "retrieval", "context-build": "retrieval", "design-context": "retrieval",
          "retrieve": "remote", "semantic-search": "remote", "rerank": "remote"}
LIMITS = {"heavy": 1, "retrieval": 2, "remote": 1}


def stop_process(process):
    """Give cooperative checks time to clean up, then bound the whole group."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    except ProcessLookupError:
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def process_token(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (OSError, IndexError):
        return None


def arguments(argv):
    from .quality_cli import add_parsers

    if (not isinstance(argv, list) or not argv or argv[0] not in GROUPS or len(argv) > 64
            or any(not isinstance(x, str) or "\0" in x for x in argv) or len(encode(argv)) > 8000):
        raise ValueError("Queue requires a bounded argv for an allowed quality command")
    parser = argparse.ArgumentParser(exit_on_error=False)
    add_parsers(parser.add_subparsers(dest="command", required=True))
    try:
        return parser.parse_args(argv)
    except (SystemExit, argparse.ArgumentError) as exc:
        raise ValueError("Invalid queued quality arguments") from exc


def fingerprint(root, args):
    selected = getattr(args, "source", [])
    if isinstance(selected, str):
        selected = [selected.rsplit(":", 2)[0]]
    hashes = {p: item["sha256"] for p, item in sources(root, selected, allow_empty=True).items()} if selected else {}
    for name in [getattr(args, "config", ".ai/manacost-quality.json"), "package-lock.json", "composer.lock", "go.sum"]:
        if (root / name).exists():
            hashes[name] = read_source(root, name)["sha256"]
    # Freeze selected source/config and the worktree status, not an entire project snapshot.
    result = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=normal"], cwd=root,
                            capture_output=True, timeout=10, check=False)
    if result.returncode == 0:
        hashes["git-status"] = digest(result.stdout)
        for path in getattr(args, "changed", []):
            if (root / path).is_file():
                hashes[path] = read_source(root, path)["sha256"]
    return digest(encode(hashes).encode())


class Queue:
    def __init__(self, store):
        self.directory = private_dir(store.directory.parent / "quality-jobs")
        path = self.directory / "queue.sqlite3"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError("Invalid queue database")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, root TEXT, state_dir TEXT, argv TEXT, fingerprint TEXT,
            category TEXT, status TEXT, created REAL, timeout INTEGER,
            owner INTEGER, owner_token TEXT, child INTEGER, child_token TEXT,
            cancel INTEGER DEFAULT 0, finished REAL, result TEXT)""")
        self.db.commit()

    def close(self):
        self.db.close()

    def submit(self, store, argv, timeout=120):
        args = arguments(argv)
        if type(timeout) is not int or not 1 <= timeout <= 1800:
            raise ValueError("Job timeout must be 1–1800 seconds")
        hashed = fingerprint(store.root, args)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            previous = self.db.execute("SELECT id FROM jobs WHERE root=? AND argv=? AND fingerprint=? "
                                       "AND status IN ('queued','running') AND cancel=0",
                                       (str(store.root), encode(argv), hashed)).fetchone()
            if previous:
                return {"id": previous[0], "deduplicated": True}
            if self.db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 100:
                raise ValueError("Queue capacity reached (100 active jobs)")
            if self.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= 1000:
                raise ValueError("Queue history capacity reached; explicitly archive this state before adding jobs")
            identifier = uuid.uuid4().hex
            self.db.execute("INSERT INTO jobs(id,root,state_dir,argv,fingerprint,category,status,created,timeout) "
                            "VALUES(?,?,?,?,?,?,'queued',?,?)", (identifier, str(store.root), str(store.directory.parent),
                                                               encode(argv), hashed, GROUPS[argv[0]], time.time(), timeout))
        return {"id": identifier, "deduplicated": False}

    def finish(self, identifier, status, result):
        with self.db:
            self.db.execute("UPDATE jobs SET status=?,finished=?,result=? WHERE id=?",
                            (status, time.time(), encode(result), identifier))

    def cancel(self, root, identifier):
        with self.db:
            changed = self.db.execute("UPDATE jobs SET cancel=1, status=CASE WHEN status='queued' THEN 'cancelled' "
                                      "ELSE status END WHERE id=? AND root=? AND status IN ('queued','running')",
                                      (identifier, str(root))).rowcount
        return {"id": identifier, "cancellation_requested": bool(changed)}

    def status(self, root, identifier=None):
        if identifier:
            rows = self.db.execute("SELECT id,category,status,cancel,created,finished,result FROM jobs WHERE root=? AND id=?",
                                   (str(root), identifier))
        else:
            rows = self.db.execute("SELECT id,category,status,cancel,created,finished,result FROM jobs WHERE root=? "
                                   "ORDER BY created DESC LIMIT 30", (str(root),))
        return [{**dict(row), "result": json.loads(row["result"]) if row["result"] else None} for row in rows]

    def claim(self, root):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            # Kill only orphaned process groups whose PID start time still matches.
            for row in self.db.execute("SELECT * FROM jobs WHERE status='running'").fetchall():
                if process_token(row["owner"]) == row["owner_token"]:
                    continue
                if row["child"] and process_token(row["child"]) == row["child_token"]:
                    try:
                        if os.getpgid(row["child"]) == row["child"]:
                            os.killpg(row["child"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                self.db.execute("UPDATE jobs SET status='interrupted',finished=?,result=? WHERE id=?",
                                (time.time(), encode({"reason": "worker stopped; explicit resubmission required"}), row["id"]))
            counts = dict(self.db.execute("SELECT category,COUNT(*) FROM jobs WHERE status='running' GROUP BY category"))
            for row in self.db.execute("SELECT * FROM jobs WHERE root=? AND status='queued' AND cancel=0 "
                                       "ORDER BY created", (str(root),)).fetchall():
                if counts.get(row["category"], 0) < LIMITS[row["category"]]:
                    self.db.execute("UPDATE jobs SET status='running',owner=?,owner_token=? WHERE id=?",
                                    (os.getpid(), process_token(os.getpid()), row["id"]))
                    return dict(row)
        return None

    def run(self, row):
        identifier = row["id"]
        argv = json.loads(row["argv"])
        root = Path(row["root"])
        if fingerprint(root, arguments(argv)) != row["fingerprint"]:
            self.finish(identifier, "stale", {"reason": "selected source/config changed; resubmit"})
            return
        output = self.directory / (identifier + ".log")
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / "context_economy.py"),
                   "--project", str(root), "--state-dir", row["state_dir"], *argv]
        # Indexing and heavy verification yield CPU to interactive work.
        if row["category"] == "heavy":
            command = ["nice", "-n", "10", *command]
        started = time.monotonic()
        state = "completed"
        reason = None
        with output.open("xb") as stream:
            os.chmod(output, 0o600)
            process = subprocess.Popen(command, cwd=root, stdout=stream, stderr=stream, start_new_session=True)
            with self.db:
                self.db.execute("UPDATE jobs SET child=?,child_token=? WHERE id=?",
                                (process.pid, process_token(process.pid), identifier))
            try:
                while process.poll() is None:
                    cancelled = self.db.execute("SELECT cancel FROM jobs WHERE id=?", (identifier,)).fetchone()[0]
                    if cancelled or time.monotonic() - started > row["timeout"] or output.stat().st_size > 2_000_000:
                        state = "cancelled" if cancelled else "failed"
                        reason = "cancelled" if cancelled else "timeout" if time.monotonic() - started > row["timeout"] else "output limit"
                        stop_process(process)
                        break
                    time.sleep(0.05)
                code = process.wait()
            finally:
                if process.poll() is None:
                    stop_process(process)
        if code != 0 or output.stat().st_size > 2_000_000:
            state = "cancelled" if state == "cancelled" else "failed"
        self.finish(identifier, state, {"exit_code": code, "reason": reason, "output": str(output),
                                       "seconds": round(time.monotonic() - started, 3)})


def execute(store, args):
    queue = Queue(store)
    try:
        if args.command == "queue-submit":
            return queue.submit(store, json.loads(read_source(store.root, args.payload)["text"]), args.timeout)
        if args.command == "queue-cancel":
            return queue.cancel(store.root, args.id)
        if args.command == "queue-status":
            return {"jobs": queue.status(store.root, args.id)}
        completed = 0
        if not 1 <= args.max_jobs <= 100 or not 0 <= args.idle_timeout <= 60:
            raise ValueError("Worker requires 1–100 jobs and at most 60 idle seconds")
        deadline = time.monotonic() + args.idle_timeout
        while completed < args.max_jobs:
            row = queue.claim(store.root)
            if row:
                try:
                    queue.run(row)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    queue.finish(row["id"], "failed", {"error": type(exc).__name__, "reason": "job could not execute"})
                completed += 1
                deadline = time.monotonic() + args.idle_timeout
            elif time.monotonic() >= deadline:
                break
            else:
                time.sleep(0.1)
        return {"processed": completed, "jobs": queue.status(store.root)}
    finally:
        queue.close()
