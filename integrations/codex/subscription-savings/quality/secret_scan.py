#!/usr/bin/env python3
"""Run Gitleaks on explicit source snapshots, never on a server/repository inventory."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_economy.common import read_source  # noqa: E402

if not 1 <= len(sys.argv[1:]) <= 100:
    raise SystemExit("Select 1–100 explicit source files")
with tempfile.TemporaryDirectory(prefix="quality-secrets-") as directory:
    for name in sys.argv[1:]:
        selected = read_source(Path.cwd(), name)
        target = Path(directory) / selected["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(selected["text"])
    raise SystemExit(subprocess.run(["gitleaks", "dir", "--redact", "--no-banner", "--exit-code", "1", directory],
                                   timeout=120).returncode)
