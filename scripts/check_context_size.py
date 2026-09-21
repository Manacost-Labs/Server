"""Bound first-party permanent instructions in bytes, not model tokens."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMITS = {"AGENTS.md": 4500, "integrations/cursor/manacost-global.mdc": 3000}


def main():
    failures = []
    for relative, limit in LIMITS.items():
        size = (ROOT / relative).stat().st_size
        print(f"{relative}: {size}/{limit} UTF-8 bytes (not token usage)")
        if size > limit:
            failures.append(relative)
    if failures:
        raise SystemExit("Permanent context budget exceeded: " + ", ".join(failures))


if __name__ == "__main__":
    main()
