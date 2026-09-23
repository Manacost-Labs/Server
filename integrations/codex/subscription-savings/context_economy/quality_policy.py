"""Deterministic trigger selection; no model calls or automatic escalation."""

import fnmatch
from pathlib import Path

from . import packing

MODULES = Path(__file__).resolve().parents[1] / "quality/guards"
RISKS = {"low": 0, "medium": 1, "high": 2, "critical": 3}
TIERS = {"fast": 0, "medium": 1, "heavy": 2}


def route(paths, task_type="implementation", risk="low", stack=None, budget=1500):
    if risk not in RISKS or task_type not in {"mechanical", "implementation", "debugging", "ui", "release",
                                            "dependency", "architecture", "performance"}:
        raise ValueError("Unknown task type or risk")
    if not paths or len(paths) > 100:
        raise ValueError("Routing requires 1–100 explicit changed/requested paths")
    if any(Path(p).is_absolute() or ".." in Path(p).parts for p in paths):
        raise ValueError("Changed paths must be project relative")
    stacks = set()
    for path in paths:
        suffix = Path(path).suffix
        if suffix == ".go" or Path(path).name in {"go.mod", "go.sum"}:
            stacks.add("go")
        if suffix == ".php" or Path(path).name in {"composer.json", "composer.lock"}:
            stacks.add("wordpress")
        if suffix in {".js", ".jsx", ".ts", ".tsx"}:
            stacks.add("nextjs")
    if stack:
        if stack not in {"nextjs", "go", "wordpress"}:
            raise ValueError("Unsupported stack")
        stacks.add(stack)
    assets = any(Path(p).suffix in {".png", ".jpg", ".webp", ".avif"} for p in paths)
    ui = assets or task_type == "ui" or any(Path(p).suffix in {".tsx", ".jsx", ".css", ".scss", ".svg"} for p in paths)
    security = any(any(word in p.casefold() for word in ("auth", "session", "permission", "payment", "migration"))
                   for p in paths)
    effective_risk = "high" if security and RISKS[risk] < 2 else risk
    tier = "heavy" if RISKS[effective_risk] >= 2 or task_type in {
        "release", "dependency", "architecture", "performance"} else (
            "medium" if RISKS[effective_risk] == 1 else "fast")
    names = []
    if ui:
        specialized = ("assets" if assets else "svg" if any(p.endswith(".svg") for p in paths)
                       else "tokens" if any("token" in p.lower() for p in paths)
                       else "visual-regression" if task_type == "release"
                       else "components" if any("component" in p.lower() for p in paths) else "base")
        names.append("design/" + specialized)
    if security:
        names.append("engineering/shared-security")
    for language in sorted(stacks):
        kind = "performance" if task_type == "performance" and language in {"go", "nextjs"} else "base"
        names.append("engineering/" + language + "-" + kind)
    if task_type != "mechanical" and len(names) < 3:
        names.insert(0, "token/retrieval")
    if not names:
        names = ["token/base"]
    # Multi-stack tasks are explicitly split when their required modules cannot fit.
    if len(names) > 3:
        raise ValueError("More than three applicable modules; split the cross-stack task into bounded phases")
    modules = [{"id": name, "text": (MODULES / (name + ".md")).read_text()} for name in names]
    count = sum(packing.estimate(m["text"]) for m in modules)
    if count > budget:
        raise ValueError("Guard instructions exceed the requested budget")
    return {"modules": modules, "estimated_tokens": count, "stacks": sorted(stacks), "ui": ui,
            "risk": effective_risk, "risk_reason": "sensitive path" if security else "requested risk",
            "tier": tier, "model_calls": 0, "network_calls": 0}


def matches(paths, patterns):
    return not patterns or any(fnmatch.fnmatchcase(path, pattern) or
                              (pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]))
                              for path in paths for pattern in patterns)
