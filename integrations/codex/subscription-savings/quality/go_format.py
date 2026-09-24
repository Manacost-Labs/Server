#!/usr/bin/env python3
"""gofmt exits zero for differences; turn its read-only output into a real gate."""
import subprocess
import sys
from pathlib import Path

if not sys.argv[1:] or any(not name.endswith(".go") or not Path(name).is_file() for name in sys.argv[1:]):
    raise SystemExit("Select explicit existing Go files")
process = subprocess.run(["gofmt", "-l", *sys.argv[1:]], capture_output=True, text=True, timeout=30)
print(process.stdout or process.stderr, end="")
raise SystemExit(process.returncode or bool(process.stdout.strip()))
