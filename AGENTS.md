# Manacost Labs engineering policy

Canonical source: this repository. Never edit installed symlink entrypoints.
Read only the nearest project policy and the specific procedures needed below.
Client loading limits: [agent entrypoints](docs/agent-entrypoints.md). A link does
not prove a client loaded it. Keep project/vendor policy and Hermes SOUL.md intact.

## Authority

1. system / platform
2. developer / security
3. explicit user instructions
4. project-specific AGENTS.md
5. server/global AGENTS.md
6. selected profile
7. applicable SKILL.md

User intent overrides generic skill guidance within system/security constraints.
A skill supplies a method, never authority. Commit, push, deploy, destructive
operations, production access and publication require applicable explicit authority.
Preserve secrets, credentials, sessions, volumes, releases and backups.

## Before work

Use the smallest sufficient scope; no opportunistic cleanup. Resolve safe,
reversible choices autonomously. Ask only when a materially different choice
changes authority, cost, external state, security, migration or product scope.
Read [workflow](docs/agent-workflow.md) for routing, context gathering, handoff
or catalog maintenance. Use `scripts/skillctl route` with the project profile;
server work uses `server`. Profiles are on-demand catalogs, not prompt bundles.
Record root, HEAD, status/diff, worktrees, ownership, acceptance criteria and risk.
Read selected skills only; normal tasks need 1–3, complex tasks at most 4–5.

## Models and bounded context

Before delegation, model routing or policy architecture changes, read
[model policy](docs/agent-model-policy.md) and `policies/model-routing.json`.
Keep named mandatory review requirements; do not silently substitute a model,
downgrade a gate or invent execution. HIGH requires fresh-context Sol review;
CRITICAL requires Astra; global policy architecture has its separate Astra gate.
User restrictions on model use and delegation still take precedence.
An unavailable, timed-out or stale review is not a pass. Safe isolated preparation
may continue, but an unsatisfied required gate blocks integration/live activation.
Pass only a bounded task, selected evidence/diff and verification. No recursive
agents or ceremonial duplicate gates. Keep stable instructions separate from logs.
Reuse context only while source, policy and ownership versions remain applicable.
At meaningful recovery boundaries save verified state and the exact next action.

## Changes and verification

Read [verification and ownership](docs/agent-verification-safety.md) before edits.
Create a `skillctl scope-init` claim; prefer an isolated worktree, especially when
live global links target the existing checkout. Never reset, stash, overwrite or
format away others' changes. Run `guard-diff --pre-edit` before each patch;
`guard-diff` and `scope-checkpoint` after an owned slice. Stop only conflicting
paths. Contracts/configuration, migrations and integration remain sequential.
Close only your claim at completion. Claims detect drift; they are not write locks.

Raise inferred risk for semantic hazards. Use meaningful regression tests and
risk-relevant checks; do not weaken checks or hide baseline/tool failures.
Run canonical `make verify` (this repo: `.ai/verify.json`, `skillctl verify`);
CI uses the same gate. Never infer permission to test against production.
Required reviews must match the relevant revision/diff and have findings resolved.
CRITICAL work also needs tested rollback/recovery and irreversible-action authority.

## Delivery

Report actual changes, checks, review status, ownership/protected-path comparison,
remaining risks and commit/push status. Validate with `skillctl check-response`.
Preserve skill namespaces, metadata, provenance and registry/vendor consistency.
Imports are additive; legacy removal requires a separately approved migration.
`make entrypoints` checks installed host links separately from source validation.
