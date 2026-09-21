# Detailed agent policy

Required when the corresponding operation is in scope. These procedures preserve the original policy; the root AGENTS.md routes to them.

## Models and agents

Role selectors, risk, skill budgets and brief fields live in
[policies/engineering.json](policies/engineering.json). Provider identifiers
exist in one [tier table](skills/engineering/synthesis/synthesis-model-tiers/tiers.yaml);
resolve them with `skillctl models`, then check the client's advertised models.

- Sol is the everyday lead: implementation, contracts, integration and ownership.
- Luna is the compact Context Scout and optional medium-risk reviewer.
- Terra implements bounded, well-specified, disjoint work; no unknown architecture.
- Astra handles global rules, difficult architecture/root cause and critical review.

Global policy/skills architecture additionally requires a bounded Astra
architecture assessment, distinct from Sol's correctness review. The exact
triggering artifacts are configured in `architecture_review`. Role selectors
are exact: generic tier fallbacks cannot satisfy a named mandatory review or
silently turn a bounded worker into the lead.

Trivial LOW/MEDIUM tasks need no agent. Normal tasks use a scout when available. Complex
tasks may add useful bounded workers. HIGH requires fresh-context Sol review;
CRITICAL requires Astra review. Risk and complexity are independent: even a
small authentication change is not automatically LOW. MEDIUM review is optional.
Never create two ceremonial gates for every edit or duplicate the lead's work.
Workers/reviewers are leaf agents: no recursive scouts or child gates.

Pass only scope, relevant evidence, tests and acceptance criteria. A reviewer
receives the compact brief and diff, not the entire repository. Reviews cover
correctness, regression, security, architecture and unnecessary complexity.
The lead validates findings and owns the result; workers never silently integrate.
Use actual runtime statuses: timeout is not model unavailability. Retry at most
once when useful. A mandatory review must be completed against the relevant
revision/diff, with required findings resolved, before integration, activation
of live global policy, or release. Failed, timed-out, unavailable or stale
reviews leave the gate unsatisfied. Continue safe preparation and request
coordination only where this blocks activation. Prepare global policy changes
in an isolated candidate checkout when installed links point to the live one.
Never invent execution or silently downgrade it.
