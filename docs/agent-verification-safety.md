# Detailed agent policy

Required when the corresponding operation is in scope. These procedures preserve the original policy; the root AGENTS.md routes to them.

## Risk and executable verification

`skillctl risk <root>` conservatively infers path/task risk. Agents must raise
risk for semantic hazards filenames cannot reveal; a hint cannot lower it.
LOW: focused checks. MEDIUM: relevant lint/types/unit tests. HIGH: full relevant
suite, safe integration, security and independent review. CRITICAL adds tested
rollback/recovery and explicit authority for irreversible operations.

Bug regressions need meaningful regression tests. Complex business logic is
test-first; use TDD for medium/high-risk behavior where it protects correctness.
A low-risk reversible edit can use focused verification. No tests written just
to mirror implementation or repeated full suites without changed evidence.

Run the project's canonical `make verify` (or its stronger existing equivalent).
CI must invoke that same entrypoint. This repository uses `.ai/verify.json` and
`skillctl verify`; see [project opt-in](docs/engineering-system.md). Missing
required tools, timed-out checks and baseline failures are not passes. Run only
stack/risk-relevant security/browser/API checks; never test against production
by inference. Do not weaken rules or hide failures to manufacture green output.

## Parallel-session safety

Before implementation create an explicit scope with `skillctl scope-init`.
Prefer separate worktrees; claims prevent cooperating sessions taking overlapping
paths in one worktree. Never reset, stash, overwrite or format away other work.
Before each patch run `guard-diff <scope> --pre-edit`; after an owned atomic
slice run `guard-diff`, then `scope-checkpoint`. Recheck status and ownership.
Stop only the conflicting slice, coordinate exact paths, preserve unrelated work.
Migrations, shared contracts/configuration and integration stay sequential.
Before commit run `guard-diff`; after the task release only your `scope-close`
claim. The guard detects drift, not every external writer; it is not a sandbox
or atomic write lock. Never label uncoordinated shared writes safe.
