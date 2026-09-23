# Completion evidence — 2026-09-23

The user approved `/home/debian/four-document-quality-completion-plan.md` and
said “реализовай”. All four documents and both applications remain in scope.
This note supersedes the older verification.md and sealed overlays for current
implementation status. The user subsequently declined Sol review and explicitly
requested integration, verification and Git push. No independent Sol review was
run; this is an explicit user exception to the repository's HIGH review gate,
not a passed review.

## Source and ownership

Server: `/srv/projects/tools/skills-four-document-quality-candidate-20260923`,
branch `codex/four-document-quality-candidate-20260923`, base `07ca7523660e`.
Claim: `/tmp/four-document-quality-20260923-v3.scope.json`.
WordPress: `/srv/projects/tasks/hs-manacost-four-document-quality-completion-20260923`,
branch `codex/four-document-quality-completion-20260923`, base `487d9394`.
Claim: `/tmp/hs-manacost-quality-completion-20260923.scope.json`.
HearthPulse: `/srv/projects/tasks/hearthpulse-four-document-quality-completion-20260923`,
branch `codex/four-document-quality-completion-20260923`, base `7656c82`.
Claim: `/tmp/hearthpulse-quality-completion-20260923.scope.json`.
The temporary HearthPulse reference-only claim is closed; the screenshot is
owned under scripts/quality/references by the main task claim.

The old divergent HearthPulse task no longer exists. Before creating the new
worktree, canonical HEAD and origin/main both equalled 7656c82; both previous
2c6977b and cde7e68 were confirmed ancestors. No unrelated history was merged.
Native work preflight passed. No subagent or model switching was used.

## Verified implementation

- Codex 0.156.1 strict configuration and seven profiles; source pin and CI match
  the actual host. No live agent/model hook session was invoked.
- Local AST retrieval, explicit OpenRouter semantic fallback/native rerank,
  complete bounded definitions, stale SHA rejection, cached repeat calls.
  Original live public-code evidence remains retrieval-openrouter.md: four calls,
  $0.00049824 actual provider cost, changed-query vector reuse, zero-call repeat.
- TypeScript compiler-bound caller/callee aliases; non-TS references are explicitly
  labelled candidates. Incremental indexing handles changed/deleted files and
  removal of a previously indexed directory.
- Durable SQLite jobs: deduplication, source/config fingerprints, cancellation,
  timeouts/output bounds, orphan handling; limits heavy=1, retrieval=2, remote=1.
  Running cancellation grants two seconds for cleanup before killing its group.
- Offline o200k_base tokenizer, pinned tiktoken 0.14.0, provisioned at build time.
  Runtime constructs the encoder from local hash-checked ranks, with no network
  loader. Context counts are a proxy plus 15%, not subscription usage or a bound
  guaranteed for every model. Missing artifacts retain the conservative fallback.
- Project clients validate commands/paths and select installed or candidate
  releases. Russian component-purpose keywords and source-hashed screenshots work.
  Actual design-context results: HeaderProfileButton (438 estimated tokens),
  AdminUiPatterns (526). Both project design gates passed using staged release v2.
- Real rembg CPU/U2Net inference ran with socket connections forbidden and produced
  alpha 0..255. All five asset presets produced 20 AVIF/WebP variants while keeping
  the original HearthPulse banner SHA unchanged. Evidence:
  `/tmp/four-document-assets-real-20260923/summary.json`.
- Four fixed real-code queries retained complete project instructions and verified
  packets of 3967, 3889, 6753 and 6391 estimated tokens, with zero model calls:
  `/tmp/four-document-completion-benchmark-20260923.json`.

Server canonical evidence: `/tmp/four-document-completion-final-server-verify-20260923.log`
passed 29/29 HIGH-risk checks, 285 unittest cases, no skipped checks. The final
client regression launches both default-family plan and verify through the real
CLI. It caught and fixed the invalid `--family all` argument; unspecified family
now correctly means both. A separate literal-argv regression covers metacharacters.
Selected Semgrep output is empty for server and application clients/diagnostics.
The exact client exception documents a local operator-selected executable with
explicit argv and no shell, not a web-input command boundary.

## Application evidence

HearthPulse: native `verify:release` and the full authenticated/mobile browser
observatory passed. Logs: `/tmp/hearthpulse-quality-release-20260923.log` and
`/tmp/hearthpulse-quality-browser-20260923.log`. CI's release gate now validates
its project registry. Native browser references remain fixture/synthetic-identity
evidence; they do not certify production data.

WordPress: `make check`, extended `make code-quality`, Composer audit, disposable
WordPress integration, and browser tests passed. Visual: 14 passed, 2 intentional
skips (matrix already run on desktop, desktop-only header), no baseline update.
The mobile editor discrepancy was port-dependent permalink reflow, corrected
only in test normalization, with the real version button asserted visible.
Logs: `/tmp/hs-manacost-quality-check-final.log`,
`/tmp/hs-manacost-quality-extended-final.log`,
`/tmp/hs-manacost-quality-integration-tests-20260923.log`,
`/tmp/hs-manacost-quality-visual-final-20260923.log`.

PHPUnit now has 22 real metadata-cache fixture scenarios. Infection initially
failed 67.92%, exposed missing boundary tests, then passed 75.47% with thresholds
70%, one worker, no source-PHP behavior changes. Log:
`/tmp/hs-manacost-infection-quality-final.log`. Rector ratchets six pre-existing
proposals using source and diff hashes. Deptrac has zero violations and two
explicit Newspaper adapters; 4442 unassigned global/vendor tokens remain visible.
PHPStan's existing 29-item baseline is unchanged. Optional mutation CI uses CLI
Xdebug; local verification extracted Debian Xdebug into a temporary toolchain,
without changing system/production PHP.

Query Monitor 4.0.7 ran only in the disposable stack: 24 panels; the final repeat recorded 50 SQL queries,
zero SQL errors, 144 hooks, 80 script assets (earlier sample: 36/110). Only numeric metrics/counts exported.
Four admin screens each passed five-sample native performance budgets. Report
`before` fields are configured budget baselines, not measured improvement.
Artifacts are under the WordPress worktree `.artifacts/quality-diagnostics` and
`.artifacts/quality-performance`. Mixed WPScan hit its limit; the bounded passive
rerun exited 0 but the wrapper correctly returned 2 because its proprietary
advisory API token is unavailable. Standard WPScan configuration paths and the
current environment contain no key. User said “сам сделай”: a separate public
[WPVulnerability adapter](https://docs.wpvulnerability.com/) now checks exact local
core/plugin/theme versions without registration. It uses PHP version_compare,
bounded requests/responses, preserves raw response hashes, and never labels its
data as the WPScan database. Seven meaningful regression tests passed.

Actual public inventory lookup: one reported advisory for fixture WordPress 6.9.7
(CVE-2026-93485), no matching version advisories for Classic Editor 1.6.7 or
Newspaper 12.7.3, and three unknown private plugins. Newspaper_new -> newspaper
is an exact alias verified from its vendor/text-domain header, not a guessed
normalization. The diagnostic returns failure (2), correctly. This is not a
production inventory or exploit confirmation; upgrading WordPress is a separate
application change, not hidden inside quality-tool adoption. API and schema errors,
unknown components, closed components and known advisories cannot produce a pass.
Log: `/tmp/hs-manacost-advisories-live-20260923.log`; private worktree report:
`.artifacts/quality-diagnostics/public-advisories/summary.json`.

Query Monitor now installs with the operator's UID/GID to permit later cleanup.
The named browser container is stopped in finally, including timeout paths; its
second real run and stack cleanup passed in
`/tmp/hs-manacost-query-monitor-final-20260923.log`.

The task-owned stack hs-manacost-integration-cc6e9febbe75 on loopback 18883 was
stopped after verification. Cleanup log: `/tmp/hs-manacost-quality-stack-cleanup.log`.
Generated test credentials remain private; do not print runtime.env.

## Release and remaining work

Final staged immutable release: `/tmp/manacost-quality-completion-release-v4-20260923`.
Manifest verification passed; source snapshot:
`fc34ccd88c2ec4690f47315a2ccbfa89a2a9194972cfd769f2c91c6358481903`.
It contains its own Python/Node/CPU-rembg dependencies, pinned model and offline
tokenizer. Both actual clients' default planning and design gates passed. Its own
asset CLI produced four cutout variants plus metadata from the real banner,
leaving the source unchanged. Earlier v1/v2/v3 directories are historical; v3
predates the default-family client fix and must not be activated.

Coupled rollback smoke: `/tmp/four-document-quality-coupled-rollback-v2-20260923/summary.json`.
The old launcher, new launcher and restored old launcher all ran the same legacy
report successfully with identical output; both new app clients planned on the
new release. The installed link AND wrapper remained byte-for-byte unchanged.
The live old release uses system Python and lacks the new guard commands/venv:
activation must replace its launcher with the new release-aware frontdoor, then
adopt application overlays. Rollback must revert the two application overlays,
restore the old launcher, then restore the old current link. A pointer-only
rollback with new app clients is incompatible, and the initial failed smoke is
preserved. Source overlays are checked forward/reverse on isolated exact bases.

Reviewable delivery: `/home/debian/four-document-quality-delivery-20260923` contains
all three source patches/archives, file hashes, application/release evidence,
rollback instructions and a context-budget-checked review brief. `acceptance.json`
contains all 142 source sections with explicit implementation/evidence/limitations.
No row claims live activation. The later user instruction authorizes source
integration and Git push while declining Sol review. Treat the latter as an
explicit exception, never as an executed or successful review. Do not infer
production deployment from the request to push source changes.
The installed current still targets `2026-09-22-quality-v2-07ca752`. No commit, push,
production deployment, senior-model invocation or subagent was performed.
