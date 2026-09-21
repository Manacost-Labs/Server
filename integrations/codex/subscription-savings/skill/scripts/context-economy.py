#!/usr/bin/env python3
"""Keep an optional symlinked skill bound to its accompanying implementation."""

import runpy
import sys
from pathlib import Path

integration = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(integration))
runpy.run_path(str(integration / "context_economy.py"), run_name="__main__")
