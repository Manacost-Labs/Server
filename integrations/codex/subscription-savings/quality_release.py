#!/usr/bin/env python3
"""Prepare a new immutable quality release; never switch installed entrypoints."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def prepare(source, output, install_dependencies=False, background_model=None):
    source, output = Path(source).resolve(), Path(output).absolute()
    if background_model:
        from quality.background_remove import MODEL_SHA256
        background_model = Path(background_model)
        if not install_dependencies:
            raise ValueError("Asset provisioning requires --install-dependencies")
        if (not background_model.is_file() or background_model.stat().st_size != 4574861
                or hashlib.sha256(background_model.read_bytes()).hexdigest() != MODEL_SHA256):
            raise ValueError("Select the pinned local u2netp model")
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("Select a new release directory without symlink ancestors")
    names = subprocess.check_output(["git", "-C", str(source), "ls-files", "--cached", "--others",
                                     "--exclude-standard", "-z", "--", "."]).decode().split("\0")
    files = []
    for name in sorted(set(names) - {""}):
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or any(part in {"node_modules", ".venv", "__pycache__"} for part in path.parts):
            raise ValueError("Unexpected path in release source")
        if path.name.startswith(".env") or path.name in {"auth.json", "credentials.json", "wp-config.php"}:
            raise ValueError("Credential/config data cannot enter a quality release")
        original = source / path
        if original.is_symlink() or not original.is_file() or original.stat().st_size > 2_000_000:
            raise ValueError("Release requires regular bounded source files")
        files.append((name, original))
    if not any(name == "context_economy.py" for name, _ in files):
        raise ValueError("Release source is missing its main entrypoint")
    output.mkdir(mode=0o700, parents=True)
    manifest = {"state": "prepared-source; dependencies not installed", "files": [],
                "base_commit": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip(),
                "source": str(source), "activated": False}
    for name, original in files:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        target.chmod(0o755 if original.stat().st_mode & 0o111 else 0o644)
        manifest["files"].append({"path": name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    manifest["snapshot_sha256"] = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()
    (output / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if install_dependencies:
        with (output / "dependency-install.log").open("xb") as log:
            os.chmod(log.name, 0o600)
            commands = [[sys.executable, "-m", "venv", str(output / ".venv")],
                        [str(output / ".venv/bin/python"), "-m", "pip", "install", "--disable-pip-version-check",
                         "--no-input", "-r", str(output / "requirements-quality.txt")],
                        ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefix", str(output / "quality")]]
            for argv in commands:
                subprocess.run(argv, check=True, stdout=log, stderr=log, timeout=600)
            tokenizer = output / "quality/tokenizer-cache"
            subprocess.run([str(output / ".venv/bin/python"), str(output / "quality/provision_tokenizer.py"),
                            "--output", str(tokenizer)], check=True, stdout=log, stderr=log, timeout=120)
            manifest["artifacts"] = [{"path": str(path.relative_to(output)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                     for path in sorted(tokenizer.iterdir())]
            if background_model:
                for argv in ([sys.executable, "-m", "venv", str(output / ".assets-venv")],
                             [str(output / ".assets-venv/bin/python"), "-m", "pip", "install",
                              "--disable-pip-version-check", "--no-input", "-r", str(output / "requirements-assets.txt")]):
                    subprocess.run(argv, check=True, stdout=log, stderr=log, timeout=600)
                target = output / "quality/models/u2netp.onnx"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(background_model, target)
                manifest["artifacts"].append({"path": "quality/models/u2netp.onnx", "sha256": MODEL_SHA256,
                                             "source": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"})
        manifest["state"] = "prepared; smoke verification required"
        manifest["python"] = subprocess.check_output([str(output / ".venv/bin/python"), "--version"], text=True).strip()
        manifest["installed_python_packages"] = subprocess.check_output(
            [str(output / ".venv/bin/python"), "-m", "pip", "freeze"], text=True).splitlines()
        (output / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify(output):
    root = Path(output).resolve()
    manifest = json.loads((root / "release-manifest.json").read_text())
    mismatches = []
    actual_snapshot = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()
    if actual_snapshot != manifest["snapshot_sha256"]:
        mismatches.append("release-manifest.json:snapshot_sha256")
    for item in manifest["files"] + manifest.get("artifacts", []):
        path = Path(item["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Invalid manifest path")
        target = root / path
        if (target.is_symlink() or not target.resolve().is_relative_to(root) or not target.is_file()
                or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]):
            mismatches.append(item["path"])
    return {"ok": not mismatches, "mismatches": mismatches, "snapshot_sha256": manifest["snapshot_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--install-dependencies", action="store_true")
    parser.add_argument("--background-model", type=Path, help="Copy pinned local u2netp and install locked CPU-only rembg")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(args.output) if args.verify else prepare(args.source, args.output, args.install_dependencies, args.background_model)
        print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))
        return int(result.get("ok") is False)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Release preparation failed ({type(exc).__name__}); existing releases unchanged", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
