# Verification evidence

Canonical gate: `VERIFY_RISK=HIGH make verify`, with the isolated quality Python
environment, locked quality Node binaries and supported Codex 0.153.0 on PATH.

Current OpenRouter follow-up: **26/26 checks passed, no skipped checks**, with
**265 reported unittest cases**, including 13 new retrieval regressions. Log:
`/tmp/four-document-openrouter-verify-pinned-20260923.log`. The 13 cases cover
real-source provenance, AST selection, native model response validation, secret
rejection, shared budgets and cache accounting. Actual public-source inference
and its reported costs are recorded in [retrieval-openrouter.md](retrieval-openrouter.md).

The first follow-up run passed 25 checks and failed the existing CLI compatibility
gate because this host now has Codex 0.156.1 while the source requires 0.153.0:
`/tmp/four-document-openrouter-verify-20260923.log`. A genuine 0.153.0 binary was
installed only in `/tmp/four-document-codex-pinned-20260923` for the final run.
The installed server CLI and compatibility requirement were not changed. Live
activation still needs that version mismatch addressed; the passing pinned run
does not certify 0.156.1 compatibility.

Final selected-path Semgrep scan returned exit 0 without findings:
`/tmp/four-document-openrouter-semgrep-final-20260923.log`. Its SHA-1 rule initially
flagged the Git blob identifier. That one protocol-required call now states
`usedforsecurity=False` with an exact rule annotation; replacing it with SHA-256
would break Git blob verification. SHA-256 is separately retained for content
cache/provenance. Blob identity is not a signature or proof of trusted code.

Earlier baseline on 2026-09-23: **25/25 checks passed, no skipped checks**. The unittest
suites reported 252 tests in total, including 25 new quality cases and one real
browser acceptance test. The existing catalog/shell/workflow/secret gates passed.
After documentation-only evidence updates, the whitespace and secret checks were
re-run separately. The final scoped Semgrep recheck also passed:
`/tmp/four-document-quality-semgrep-final-20260923.log`.

The earlier review package `/tmp/four-document-quality-review-20260923.md` is
historical and stale after the OpenRouter changes. Its former 11,696-token
estimate is not current review evidence. No independent review was performed.

The new suite covers explicit scopes, actual multi-language AST queries and cache
invalidation, exact packet verification, bounded/specialized routing, tool
failure/missing/timeout/partial states, resources, performance NaN/missing data,
CSS/token/SVG safety, provider permissions/cost reservations/identity/embedding
caches, AVIF/WebP generation and actual SVG normalization. The browser acceptance
uses an isolated localhost fixture with real Chromium; it checks missing/stable/
changed screenshots, computed style and accessibility failures, and GameAsset.

Semgrep command `codex-semgrep` was run only on the changed retrieval, design,
asset, provider, execution and browser modules. It returned exit 0 with no
findings; log: `/tmp/four-document-quality-semgrep-20260923.log`.
This is automated static evidence, not a substitute for independent review.

Real project evidence: both fast **design** profile gates pass. HearthPulse has
33 validated tokens and three registry components; hs-manacost has 32 and four.
These checks read project source. Neither full application suite nor production
browser/security/performance testing was executed.

Actual resource smoke: `systemd-run --user --scope` with CPUQuota=100%,
MemoryMax=256M, TasksMax=128 and nice=10 ran a tiny Python command successfully.
Tests also simulate scope creation failure and require a failed gate.

During verification, SVG normalization initially retained an XML namespace
prefix that prevented SVGO dimension removal; this was fixed and regressed.
ShellCheck found empty CDPATH assignment style; it was fixed. Gitleaks stdin
lost path allowlisting and mistook the two public GitHub Action commit hashes
for Sourcegraph tokens. Only those exact workflow lines carry `gitleaks:allow`
comments; general scanning remains enabled. A WordPress UI route exceeded the
guard budget by ten estimated tokens; the small shared design module was
shortened and the real profile plus both stack/UI budgets are regression-tested.

Remaining gates/limits:

- Required independent HIGH-risk review has not occurred. User policy forbids
  automatic senior-model delegation; no review result is invented.
- Live release/entrypoints and both application's CI/UI remain unchanged.
  HearthPulse application adoption needs the documented divergent base resolved.
- Native OpenRouter embedding and rerank are configured and exercised with the
  existing credential. Optional rembg, WPScan, Query Monitor and project ecosystem
  tools are not all installed or exercised. Adapters report missing prerequisites.
- Flagged network execution is a contract, not a network sandbox. Trusted project
  check commands and provider argv can perform their own I/O. Cgroup limits do
  not constrain a separate Docker daemon's containers.
- No real-task token savings, resolved compiler call graph, screenshot embedding
  search, automatic crop correctness or comprehensive accessibility is claimed.

The scope claim protects only this candidate's owned paths. No commit, push,
production deployment, installed-release mutation or subagent call was made.
