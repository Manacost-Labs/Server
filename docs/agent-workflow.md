# Detailed agent policy

Required when the corresponding operation is in scope. These procedures preserve the original policy; the root AGENTS.md routes to them.

## Autonomy and scope

Do not block on ambiguity when a safe, reversible interpretation exists.
Infer intent from the request and repository, state material assumptions,
and finish the authorized work. Ask only when alternatives materially change
architecture, external state, destructive operations, security, production,
cost, public APIs, or data migration. Continue independent safe work meanwhile.
Prefer the smallest sufficient implementation; no opportunistic cleanup.
Commit, push, deploy and destructive actions require their own task authority.

## Preflight and routing

Read applicable global and nearest project instructions once per revision.
Record repository root, HEAD, `git status --short`, `git diff --name-only`,
worktrees, ownership, acceptance criteria and risk before editing. A dirty
worktree is not permission to overwrite another session's work.

Use `scripts/skillctl route <root> --task '<request>' --profile <profile>`.
Select the detected project profile (`skillctl plan <root>`); shared server
work uses `server`. Profiles are **on-demand catalogs**, not prompt bundles.
Read only selected canonical files, resolved with `skillctl resolve <id>`.
Typical skill budgets: trivial 0–1; normal 1–3; complex at most 4–5.
Document a concrete reason for exceptions; do not load overlapping checklists.
Explicitly requested skills take priority. Split long work into bounded phases.

## Context navigation and long sessions

For nontrivial work: Luna → narrow Graphify query when a map exists →
CodeGraph/Serena symbols when indexed/available → targeted source reads.
Validate relevant facts in source; record stale/missing maps. Never load an
entire graph.json. Missing indexes are a reason for targeted local fallback,
not for launching an unbounded indexing job. Refresh only approved code-only
maps incrementally with the Graphify skill; exclude secrets, databases, dumps,
credentials, generated/vendor content. No implicit network publication.

Scout output is compact JSON validated by `skillctl validate-brief <file>`:
goal, scope, relevant_files, symbols, dependencies, tests, constraints,
protected_paths, risks, recommended_skills (0–4), unknowns; at most 600 words.
Keep the stable policy prefix separate from task/diff/log context. Reuse briefs
only while their HEAD, diff, ownership and policy revisions still match.
At a context checkpoint save decisions, owned paths, tests/results, remaining
work and exact next action; resume from evidence, not reconstructed guesses.

## Handoff and catalog maintenance

Report: actual outcome; selected profile/skills; focused and final checks;
required agent/review status; scope/protected-path comparison; residual risks.
Keep the default response concise: `Done` (or `Status`), `Checks`,
`Git: Commit: yes/no; Push: yes/no` with a real reason when not performed,
and a concrete `Next` only when needed. Validate captured responses with
`skillctl check-response`; never claim tests, commits or MCP calls not executed.

Canonical skills contain SKILL.md frontmatter and skill.yaml metadata; preserve
namespaces, provenance, registry/inventory consistency and vendor dependencies.
Imports are additive. Remove a legacy copy only in an explicitly approved
separate migration after that project's checks pass. `make verify` checks the
catalog; `make entrypoints` separately verifies installed host links. Nothing
here grants access to secrets, authentication files or production data.
