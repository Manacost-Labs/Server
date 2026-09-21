# Local project memory

The optional adapter uses ai-memory **v2.3.2** as a loopback-only store for
explicit, verified notes. It does not run an LLM, request embeddings, import
existing conversations, or automatically summarize tool output. The existing
SQLite store remains available when the service is down. A failed mirror is
reported by `remember`; repeating that command retries the mirror without
duplicating the local note.

## Server deployment

The current server uses these identities (including linked Git worktrees):

| Memory project | Source checkout | Site |
| --- | --- | --- |
| `hearthpulse` | `/srv/projects/web/arena.hs-manacost.ru` | `hearthpulse.net` |
| `hearthstone-api` | `/srv/hs-data-api` | `api.kolodahearthstone.com` |
| `hs-manacost` | `/srv/projects/wordpress/hs-manacost.ru` | `hs-manacost.ru` |

The WordPress production directory is not the source checkout. No application
code or project AGENTS.md changes are necessary for this integration.

Release assets come from [upstream v2.3.2](https://github.com/akitaonrails/ai-memory/releases/tag/v2.3.2).
Verify the binary archive with the corresponding published `.sha256` before
extracting. This checks integrity against the release checksum, not an
independent publisher signature. The binary is installed in
`~/.local/share/ai-memory/releases/v2.3.2/`; initialize a new data directory with
`ai-memory init --data-dir ~/.local/share/ai-memory/server`.

Create a private `~/.config/codex-context-economy/projects.json` (mode 0600,
parent 0700); `CONTEXT_ECONOMY_PROJECTS` can select another registry:

```json
{
  "binary": "/home/debian/.local/share/ai-memory/releases/v2.3.2/ai-memory",
  "server_url": "http://127.0.0.1:49374",
  "data_dir": "/home/debian/.local/share/ai-memory/server",
  "token_file": "/home/debian/.config/codex-context-economy/server.token",
  "projects": [
    {
      "id": "hearthpulse",
      "root": "/srv/projects/web/arena.hs-manacost.ru",
      "git_common_dir": "/srv/projects/web/arena.hs-manacost.ru/.git"
    }
  ]
}
```

Populate all selected projects explicitly. Generate a new random bearer token
in `token_file` with mode 0600; never commit it. Before starting the service,
set these **root** keys in the initialized ai-memory `config.toml`:

```toml
embedding_provider = "none"
backfill_on_start = false
run_autowire = false
capture_assistant = false
```

Set `enabled = false` in `[auto_improve.scheduler]`, and `cold_threshold = 0.0`
in `[decay]`. Keep `observation_retention_days = 0`. Preserve the generated
`[auth]` section. Verified notes use semantic pages; the adapter independently
enforces TTL and source hashes. It never deletes stored records.

Copy this integration directory (including its `context_economy`, `skill` and
`bin/context-budget` dependencies) to a versioned local runtime, then point
`~/.local/share/codex-context-economy/current` to that version. Install
`ai-memory.service` below in `~/.config/systemd/user/`, then run
`systemctl --user daemon-reload` and `systemctl --user enable --now ai-memory`.
User lingering is required to keep it running after logout. The launcher
passes an environment allowlist, excluding inherited model keys, providers
and proxies. Runtime configuration itself must remain under the user's control.

Install a `context-economy` launcher for `current/context_economy.py`, and an
optional skill symlink from `~/.codex/skills/codex-context-economy` to
`current/skill`. Preserve existing entrypoints if they are already installed.

## Codex hook

Back up `~/.codex/config.toml` privately, then append this entry without
replacing existing hooks:

```toml
[[hooks.SessionStart]]
matcher = "*"
[[hooks.SessionStart.hooks]]
type = "command"
command = "/usr/bin/python3 /home/debian/.local/share/codex-context-economy/current/memory_hook.py"
timeout = 5
additionalContextLimit = 350
```

The hook emits only a short usage hint for configured repositories/worktrees.
It does not transmit prompts, tool arguments/results or session transcripts.
Notes are saved deliberately through `remember` at verified milestones. Restart
or start a new Codex task to load changed hook configuration; a synthetic hook
test does not prove that an already-running Desktop client has reloaded it.
Existing compaction/usage hooks are preserved and have their own behavior.

## Retrieval and limits

`remember` writes local SQLite first and then mirrors into the project's
`verified/` namespace. `recall` and `pack --query` use local matches plus up to
five ai-memory candidates. Returned project identity, TTL and current source
hashes are checked again, including in linked worktrees. Automatic summaries
and other namespaces do not qualify as verified notes. Retrieval is bounded;
an empty result does not prove that no relevant note exists. Refine the query.
The local fallback cannot expose remote-only notes while the service is down.

Project namespaces prevent accidental context mixing, not access by other
processes running as the same Unix user. The single local credential can access
all selected namespaces. Do not place secrets in notes or source references.
Memory is evidence, never a replacement for current user/project instructions.

Example from a repository root:

```sh
context-economy remember --text 'Verified project finding' \
  --evidence 'Command/result and known limits' --source README.md --ttl-days 30
context-economy recall 'specific finding' --limit 5
```

TypeSafe remains off by default. Nothing here changes the selected model or
starts Astra. Measure matched tasks with `record` and `report --end-to-end`;
fewer returned characters are not a measured subscription-quota improvement.

## Verification and rollback

Run `make verify` in the catalog. Adapter tests cover project/worktree mapping,
credential isolation, stale/expired notes, namespace filtering, offline fallback
and bounded hooks. Verify the real service separately: authenticated write /
search / read in an isolated smoke namespace, unauthenticated rejection, and
provider status showing both LLM and embedding disabled. Use a temporary local
SQLite state to verify that recall actually comes from ai-memory.

Rollback: remove only the added SessionStart handler, disable the service with
`systemctl --user disable --now ai-memory`, and unlink only the newly installed
CLI/skill entrypoints. Preserve private data, tokens, backups and existing hooks.
Restore the full config backup only when it cannot overwrite newer edits.
Do not roll back or redeploy the three applications for a memory-only change.
