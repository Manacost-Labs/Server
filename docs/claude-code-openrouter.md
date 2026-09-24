# Claude Code on this server

The native Claude Code installation and the shared `context-economy` CLI serve
different requests. Claude Code sends its own model calls through the OpenRouter
Anthropic-compatible gateway. `context-economy` uses the same existing private
credential for its opt-in embedding, rerank, and advisory calls. Its daily call
cap does **not** limit Claude Code's own model calls; those are billed by
OpenRouter separately.

Install the current official native release with `claude install latest` and
check it with `claude --version` and `claude doctor`. `claude update` follows the
selected rollout channel and can temporarily install an older version than the
latest published release. The [Anthropic releases](https://github.com/anthropics/claude-code/releases)
are the version reference.

The key stays in `~/.config/codex-context-economy/remote.env`, owned by the
current user with mode `0600`. The versioned
`integrations/codex/subscription-savings/bin/claude-openrouter-key` reads it
through the existing strict credential loader. Install a stable launcher at
`~/.local/bin/claude-openrouter-key` pointing to the corresponding file under
`~/.local/share/codex-context-economy/current/bin/`. In `~/.claude/settings.json`,
keep existing hooks and plugins and add only:

```json
{
  "apiKeyHelper": "/home/debian/.local/bin/claude-openrouter-key",
  "env": {
    "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
    "ANTHROPIC_API_KEY": ""
  }
}
```

The helper sends the credential to Claude Code on stdout. Do not place the key
itself in settings, shell profiles, project files, or logs. Claude Code may
report `loggedIn: false` in `claude auth status` because gateway credentials are
not a claude.ai login; verify with a short `claude -p` response and `/status`.
The [OpenRouter Claude Code guide](https://openrouter.ai/docs/guides/coding-agents/claude-code-integration)
documents the gateway URL and bearer authentication, and
[Anthropic's gateway guide](https://code.claude.com/docs/en/llm-gateway-connect)
documents `apiKeyHelper` and its credential precedence.

`~/.claude/CLAUDE.md` points to the canonical server policy. HearthPulse and
hs-manacost.ru each have a project `CLAUDE.md` directing Claude to the nearest
`AGENTS.md`; their local skills and the installed `context-economy` commands are
then available in Claude Code as in the other supported clients. Check the
links with `scripts/check-agent-entrypoints.sh` from the catalog, and use the
projects' own skill audits and release checks after changes.

## Task metering in Claude Code

Run `context-economy --project "$PWD" meter-start --task-id ID
--current-session --from-task-start` from Claude Code before task preparation,
then finish the interval after verification. The command selects the exact
`CLAUDE_CODE_SESSION_ID` from Claude Code's local project log when
`CLAUDECODE=1`; outside Claude Code it continues to select the exact
`CODEX_SESSION_ID`. It never chooses the newest session by timestamp. For a
helper session, pass its exact JSONL path with `--session PATH --session-format
claude` to `meter-attach`. Use `--session-format claude` with `meter-start
--session PATH` when starting from outside that session.

Claude Code writes one assistant record per streamed content block, often
repeating a request's usage. The meter counts each request once and includes
ordinary input, cache creation and cache reads in total input; cache reads are
also reported separately. The initial session file and each incremental read
are limited to 8 MiB. Start a fresh Claude session if an existing log exceeds
that bound. Incomplete usage makes the interval incomplete rather than
inventing a savings figure. Include all preparation, retry, review and helper
sessions before marking a pilot as fully covered.
