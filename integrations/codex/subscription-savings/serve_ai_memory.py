#!/usr/bin/env python3
"""Launch the pinned server with an isolated environment and explicit local config."""

import os

from context_economy.ai_memory import environment, load_config

config = load_config()
if config is None:
    raise SystemExit("Missing project registry")
os.execve(config["binary"], [config["binary"], "--data-dir", config["data_dir"],
                          "serve", "--transport", "http", "--bind", "127.0.0.1:49374",
                          "--workspace", "manacost", "--project", "system"], environment(config))
