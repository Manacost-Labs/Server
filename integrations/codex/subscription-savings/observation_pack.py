#!/usr/bin/env python3
"""Bounded local ObservationPack for Codex PostToolUse hooks."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ID_PATTERN = re.compile(r"^[0-9a-f]{24}$")
RECEIPT_ID_PATTERN = re.compile(r"ObservationPack id=([0-9a-f]{24})")
MEDIA_TYPES = {"image", "audio", "video", "blob"}


@dataclass(frozen=True)
class Config:
    base_dir: Path
    min_bytes: int = 6 * 1024
    preview_head_chars: int = 1200
    preview_tail_chars: int = 800
    ttl_seconds: int = 7 * 24 * 60 * 60
    max_storage_bytes: int = 512 * 1024 * 1024
    max_metrics_bytes: int = 8 * 1024 * 1024
    max_input_bytes: int = 64 * 1024 * 1024

    @classmethod
    def from_environment(cls) -> "Config":
        return cls(
            base_dir=Path(
                os.environ.get(
                    "CODEX_OBSERVATION_PACK_DIR",
                    "~/.local/state/codex-observation-pack",
                )
            ).expanduser(),
            min_bytes=_env_int("CODEX_OBSERVATION_PACK_MIN_BYTES", 6 * 1024),
            preview_head_chars=_env_int("CODEX_OBSERVATION_PACK_HEAD_CHARS", 1200),
            preview_tail_chars=_env_int("CODEX_OBSERVATION_PACK_TAIL_CHARS", 800),
            ttl_seconds=_env_int("CODEX_OBSERVATION_PACK_TTL_SECONDS", 7 * 24 * 60 * 60),
            max_storage_bytes=_env_int(
                "CODEX_OBSERVATION_PACK_MAX_BYTES", 512 * 1024 * 1024
            ),
            max_metrics_bytes=_env_int(
                "CODEX_OBSERVATION_PACK_MAX_METRICS_BYTES", 8 * 1024 * 1024
            ),
            max_input_bytes=_env_int(
                "CODEX_OBSERVATION_PACK_MAX_INPUT_BYTES", 64 * 1024 * 1024
            ),
        )


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = int(raw)
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _serialize_response(response: Any) -> str:
    if isinstance(response, str):
        return response
    return json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True)


def _contains_media(value: Any, depth: int = 0) -> bool:
    if depth > 30:
        return True
    if isinstance(value, dict):
        content_type = value.get("type")
        if isinstance(content_type, str) and content_type.lower() in MEDIA_TYPES:
            return True
        mime_type = value.get("mimeType", value.get("mime_type"))
        if isinstance(mime_type, str) and mime_type.lower().startswith(
            ("image/", "audio/", "video/", "application/octet-stream")
        ):
            return True
        return any(_contains_media(item, depth + 1) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_media(item, depth + 1) for item in value)
    return False


def _ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"Refusing symlink state directory: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"Invalid state directory: {path}")
    path.chmod(0o700)


def _records_dir(base_dir: Path) -> Path:
    _ensure_private_directory(base_dir)
    records = base_dir / "records"
    _ensure_private_directory(records)
    return records


def _observation_id(event: dict[str, Any], raw: str) -> str:
    digest = hashlib.sha256()
    for field in ("session_id", "turn_id", "tool_name", "tool_use_id"):
        digest.update(str(event.get(field, "")).encode("utf-8", errors="replace"))
        digest.update(b"\0")
    digest.update(raw.encode("utf-8"))
    return digest.hexdigest()[:24]


def _atomic_write_gzip(path: Path, text: str) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=".observation-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as raw_stream:
            with gzip.GzipFile(fileobj=raw_stream, mode="wb", mtime=0) as stream:
                stream.write(text.encode("utf-8"))
            raw_stream.flush()
            os.fsync(raw_stream.fileno())
        os.replace(temp_name, path)
        path.chmod(0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=".metadata-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        path.chmod(0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _append_metric(config: Config, metric: dict[str, Any]) -> None:
    _ensure_private_directory(config.base_dir)
    path = config.base_dir / "metrics.jsonl"
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.write(json.dumps(metric, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            if stream.tell() > config.max_metrics_bytes:
                keep_bytes = max(1, config.max_metrics_bytes // 2)
                stream.seek(max(0, stream.tell() - keep_bytes))
                retained = stream.read()
                if "\n" in retained:
                    retained = retained.split("\n", 1)[1]
                stream.seek(0)
                stream.truncate()
                stream.write(retained)
                stream.flush()
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _record_paths(records: Path, observation_id: str) -> tuple[Path, Path]:
    if not ID_PATTERN.fullmatch(observation_id):
        raise ValueError("Invalid observation ID")
    return (
        records / f"{observation_id}.json",
        records / f"{observation_id}.txt.gz",
    )


def _unlink_regular(path: Path) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            return
        path.unlink()
    except FileNotFoundError:
        return


def _iter_record_pairs(records: Path) -> Iterable[tuple[float, int, str, Path, Path]]:
    for metadata_path in records.glob("*.json"):
        observation_id = metadata_path.stem
        if not ID_PATTERN.fullmatch(observation_id):
            continue
        data_path = records / f"{observation_id}.txt.gz"
        if metadata_path.is_symlink() or data_path.is_symlink():
            continue
        if not metadata_path.is_file() or not data_path.is_file():
            continue
        stat = metadata_path.stat()
        size = stat.st_size + data_path.stat().st_size
        yield stat.st_mtime, size, observation_id, metadata_path, data_path


def cleanup(
    config: Config,
    now: float | None = None,
    protected_ids: set[str] | None = None,
) -> None:
    now = time.time() if now is None else now
    protected_ids = protected_ids or set()
    records = _records_dir(config.base_dir)
    pairs = list(_iter_record_pairs(records))
    for modified, _, observation_id, metadata_path, data_path in pairs:
        if observation_id not in protected_ids and modified < now - config.ttl_seconds:
            _unlink_regular(metadata_path)
            _unlink_regular(data_path)

    pairs = sorted(_iter_record_pairs(records), key=lambda item: item[0])
    total = sum(item[1] for item in pairs)
    for _, size, observation_id, metadata_path, data_path in pairs:
        if total <= config.max_storage_bytes:
            break
        if observation_id in protected_ids:
            continue
        _unlink_regular(metadata_path)
        _unlink_regular(data_path)
        total -= size


def _receipt(observation_id: str, raw: str, config: Config) -> str:
    head = raw[: config.preview_head_chars]
    tail = raw[-config.preview_tail_chars :] if config.preview_tail_chars else ""
    omitted = max(0, len(raw) - len(head) - len(tail))
    script = shlex.quote(str(Path(__file__).resolve()))
    recall_command = (
        f"python3 {script} recall {observation_id} --start-line 1 --lines 200"
    )
    return (
        f"[ObservationPack id={observation_id}] Oversized textual tool result archived locally.\n"
        f"Original: {len(raw.encode('utf-8'))} bytes; preview omitted about {omitted} characters.\n"
        f"Recall exact pages with: {recall_command}\n"
        "<untrusted-tool-output-preview>\n"
        f"{head}\n"
        f"... [{omitted} characters omitted] ...\n"
        f"{tail}\n"
        "</untrusted-tool-output-preview>"
    )


def process_event(
    event: dict[str, Any],
    config: Config,
    now: float | None = None,
) -> dict[str, Any] | None:
    now = time.time() if now is None else now
    if event.get("hook_event_name") != "PostToolUse":
        return None
    response = event.get("tool_response")
    if _contains_media(response):
        return None
    raw = _serialize_response(response)
    original_bytes = len(raw.encode("utf-8"))
    tool_name = str(event.get("tool_name", "unknown"))[:128]
    if original_bytes < config.min_bytes:
        _append_metric(
            config,
            {
                "archived": False,
                "estimated_saved_bytes": 0,
                "original_bytes": original_bytes,
                "timestamp": int(now),
                "tool_name": tool_name,
                "visible_bytes": original_bytes,
            },
        )
        cleanup(config, now=now)
        return None

    cleanup(config, now=now)
    records = _records_dir(config.base_dir)
    observation_id = _observation_id(event, raw)
    metadata_path, data_path = _record_paths(records, observation_id)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    _atomic_write_gzip(data_path, raw)
    _atomic_write_json(
        metadata_path,
        {
            "created_at": int(now),
            "data_file": data_path.name,
            "line_count": len(raw.splitlines()),
            "observation_id": observation_id,
            "original_bytes": original_bytes,
            "sha256": digest,
            "tool_name": tool_name,
        },
    )
    receipt = _receipt(observation_id, raw, config)
    visible_bytes = len(receipt.encode("utf-8"))
    _append_metric(
        config,
        {
            "archived": True,
            "estimated_saved_bytes": max(0, original_bytes - visible_bytes),
            "observation_id": observation_id,
            "original_bytes": original_bytes,
            "timestamp": int(now),
            "tool_name": tool_name,
            "visible_bytes": visible_bytes,
        },
    )
    cleanup(config, now=now, protected_ids={observation_id})
    # Codex 0.153 reliably exposes PostToolUse feedback through the legacy
    # block shape. The tool has already run; this only replaces its oversized
    # model-visible result with the receipt.
    return {"decision": "block", "reason": receipt}


def extract_observation_id(receipt: str) -> str:
    match = RECEIPT_ID_PATTERN.search(receipt)
    if not match:
        raise ValueError("Observation ID not found")
    return match.group(1)


def read_observation(base_dir: Path, observation_id: str) -> str:
    records = _records_dir(base_dir)
    metadata_path, data_path = _record_paths(records, observation_id)
    if metadata_path.is_symlink() or data_path.is_symlink():
        raise ValueError("Refusing symlink observation")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("data_file") != data_path.name:
        raise ValueError("Observation metadata mismatch")
    with gzip.open(data_path, "rt", encoding="utf-8") as stream:
        raw = stream.read()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if digest != metadata.get("sha256"):
        raise ValueError("Observation integrity check failed")
    return raw


def recall_lines(
    base_dir: Path,
    observation_id: str,
    start_line: int,
    line_count: int,
) -> str:
    if start_line < 1:
        raise ValueError("start-line must be at least 1")
    if line_count < 1 or line_count > 1000:
        raise ValueError("lines must be between 1 and 1000")
    raw = read_observation(base_dir, observation_id)
    lines = raw.splitlines(keepends=True)
    return "".join(lines[start_line - 1 : start_line - 1 + line_count])


def metrics_summary(base_dir: Path) -> dict[str, Any]:
    path = base_dir / "metrics.jsonl"
    summary = {
        "archived_results": 0,
        "estimated_saved_bytes": 0,
        "original_bytes": 0,
        "results": 0,
        "visible_bytes": 0,
    }
    if not path.exists() or path.is_symlink():
        summary["estimated_savings_percent"] = 0.0
        return summary
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            metric = json.loads(line)
        except json.JSONDecodeError:
            continue
        summary["results"] += 1
        summary["archived_results"] += int(bool(metric.get("archived")))
        for field in ("estimated_saved_bytes", "original_bytes", "visible_bytes"):
            summary[field] += max(0, int(metric.get(field, 0)))
    if summary["original_bytes"]:
        summary["estimated_savings_percent"] = round(
            100 * summary["estimated_saved_bytes"] / summary["original_bytes"], 2
        )
    else:
        summary["estimated_savings_percent"] = 0.0
    return summary


def _run_hook(config: Config) -> int:
    raw_input = sys.stdin.buffer.read(config.max_input_bytes + 1)
    if len(raw_input) > config.max_input_bytes:
        return 0
    try:
        event = json.loads(raw_input)
        if not isinstance(event, dict):
            return 0
        result = process_event(event, config)
    except Exception:
        return 0
    if result is not None:
        json.dump(result, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    config = Config.from_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    recall_parser = subparsers.add_parser("recall", help="Recall exact archived lines")
    recall_parser.add_argument("observation_id")
    recall_parser.add_argument("--start-line", type=int, default=1)
    recall_parser.add_argument("--lines", type=int, default=200)
    subparsers.add_parser("stats", help="Show cumulative context-savings metrics")
    subparsers.add_parser("cleanup", help="Apply TTL and storage cap now")
    args = parser.parse_args(argv)

    try:
        if args.command == "recall":
            sys.stdout.write(
                recall_lines(
                    config.base_dir,
                    args.observation_id,
                    args.start_line,
                    args.lines,
                )
            )
            return 0
        if args.command == "stats":
            print(json.dumps(metrics_summary(config.base_dir), indent=2, sort_keys=True))
            return 0
        if args.command == "cleanup":
            cleanup(config)
            return 0
        return _run_hook(config)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"observation-pack: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
