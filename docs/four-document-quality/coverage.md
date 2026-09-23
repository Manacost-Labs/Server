# Coverage of all four documents

Paths below are relative to `integrations/codex/subscription-savings` unless
stated otherwise. **Implemented** means executable candidate source with tests;
**existing** means the already present subsystem is reused; **adapter** means an
explicit integration contract whose external tool/model is not provisioned by
this change. These labels do not mean the live server or applications were deployed.

## 1 — Token Economy + Code Quality

| Sections | Implementation | Evidence / boundary |
| --- | --- | --- |
| 1–3: architecture, classification | `quality_policy.py`, `guard-context`, `quality-plan`; deterministic stack/risk/task selection | Router tests; zero classification model calls |
| 4–5: repo map, AST symbols | `retrieval.py`: ast-grep parses Python, Go, JS/TS/TSX and PHP; SHA/version cache | Actual multi-language parser tests; compiler-bound TS declarations/aliases/callers/callees; other languages remain syntactic candidates |
| 6: local search | Bounded BM25 `search` with query/source-hash cache | Explicit source limits; no global Zoekt service or recursive project scan |
| 7: related tests | AST call sites, enclosing test symbols, test priority in `context-build` | Regression finds a real caller and ignores a commented call; heuristic test association |
| 8: Context7 | `docs` adapter, library/version/query keys, three excerpts | Permission/preview/cache tests; requested version is reported, not falsely certified |
| 9–10: GitHub references | `reference-search`: gh code search, non-archived/licensed repositories, pinned commit/file/hash | Metadata filtering; compatibility, tests and production suitability explicitly remain unverified |
| 11–12: embeddings/reranker | Native OpenRouter Qwen3 embedding/rerank APIs, shared server credentials/ledger, local cosine ranking, bounded AST shortlist; explicit custom providers remain supported | Live public-code API/cache checks and strict response/provenance tests; see retrieval-openrouter.md |
| 13–14: caches | `quality_common.py` SQLite caches; embeddings reuse model/vector revision + source SHA + exact text across queries | Live test reused 20 vectors; exact repeat had zero calls; cached historical usage is separate from new charges |
| 15: architecture memory | Existing `remember`, `recall`, `inspect` and ai-memory adapter | Existing evidence/staleness regressions; verified ADR source can be a `--required` packet input |
| 16, 29–30: context packing/builder | `context-build`, `verify-context`, existing `pack`; explicit task and mandatory sources, definitions/callers/tests | Exact text and hash tampering tests; external docs/memory are deliberate separate steps, never automatic uploads |
| 17, 23: diff-only correction/review | Existing `focus`/`brief`, scoped changed paths, bounded failure packet with exact log pointer | Existing output/packing regressions; source review uses selected changes and verification, not all attachments |
| 18–22: deterministic quality/security/complexity | `quality_checks.py`, Go/Next.js/WordPress presets; existing project architecture/lint/security commands | Pass/fail/missing/timeout/partial tests; ecosystem tools remain project dependencies |
| 24: model selection | Existing model-routing/manual senior gates retained | No automatic model promotion or new agents; explicit user policy overrides the proposal's example ladder |
| 25–26: server resources | Shared nonblocking heavy/index lock, separate provider lock, bounded input/output, timeout; optional systemd CPU/memory/task limits | Lock regression and real temporary systemd-scope smoke; busy work returns a retryable failure instead of starting a daemon queue |
| 27–28: priorities/anti-patterns | Local evidence first, cached optional providers, no default all-tools/all-models execution | Router/provider tests; heavy/network flags are separate |
| 31–32: stack pipelines | `quality/profiles/nextjs.json`, `go.json`, plus real project profiles | Plans and argv contracts; heavyweight application suites not claimed as run |
| 33–35: quality/token results and metrics | Existing meter/pilot/benchmark; retrieval provider usage events, guard duration/status, browser measurements | Actual token usage supported; estimated context size is not measured billed tokens or a saving percentage |
| 36–37, conclusion: delivery | Shared CLI, profiles, tests and canonical CI gate delivered as one candidate | Activation and required independent review remain separate gates |

## 2 — Design Quality System

| Sections | Implementation | Evidence / boundary |
| --- | --- | --- |
| 1–4: pipeline, source of truth, semantic tokens | `design.py`: JSON tokens or canonical project CSS, aliases/cycles/missing references | Token tests and actual HearthPulse/WordPress source validation; existing palettes are preserved |
| 5–6: registry/shared system | Project-owned component registry and `quality/design-system/primitives.css` | Existing components referenced; new button/card/stack/icon primitives are opt-in, not injected into production |
| 7: CSS gate | tinycss2 nested-rule parser; token/raw-color/scale/important/duplicate/specificity/motion checks | Nested CSS/comments regression; focused contract complements project Stylelint/ESLint, not a full CSS semantic verifier |
| 8–10: computed styles/visual/screenshot workflow | `quality/browser.mjs`: computed property contracts, deterministic PNGs, explicit baseline acceptance, pixel diffs | Real Chromium test: missing baseline fails; unchanged passes; changed screen fails |
| 11–13: typography, spacing, buttons | Token/scale checks, computed dimensions and existing component registry; shared primitive geometry | Explicit selector/property assertions in browser config; no assertion that existing whole sites are visually uniform |
| 14: SVG | Safe XML validator + `svg-normalize` using pinned SVGO; explicit monochrome conversion, new output only | Entity/script/external-reference rejection and actual SVGO test |
| 15–16: motion | Shared duration/easing tokens, reduced-motion CSS; CSS transition-all rule; reduced-motion browser snapshots | Animation libraries remain an application choice; no new always-loaded dependency |
| 17–19: responsive/layout/a11y | Configured widths, overflow, computed styles, keyboard order and axe WCAG AA | Browser regression catches accessible-name and geometry failures; manual assistive-technology review still matters |
| 20–23: asset workflow/roles/presets/tools | Pillow AVIF/WebP variants; five presets; optional preprovisioned rembg; SVGO | Actual project banner: five presets/20 variants and offline pinned CPU rembg inference; original source immutable; Pillow substitutes for Sharp/imgproxy without a new image server |
| 24: GameAsset | Framework-neutral `gameAsset()` DOM component usable from React refs or WordPress modules | Browser test checks picture sources, decorative semantics, dimensions and unsafe-origin rejection |
| 25–27: harmonization/text-safe area/metadata | Saturation/blur/alpha, dominant colors, focal point, preset overlay and text-safe area in metadata/CSS | Focal heuristic is edge saliency, not semantic subject detection; inspect hero crop/contrast before baseline acceptance |
| 28–31: design context/similarity/screenshots | `design-context`: bounded lexical registry search; tokens/stories/responsive rules, screenshot path+SHA, asset preset | Registry/context tests; local screenshot references, not a visual-embedding search engine |
| 32: bounded review | Browser before/after/diff artifacts and failure report; small design context | Only selected component/evidence reaches review; screenshots are not silently auto-approved |
| 33–34: UI gate/tool choices | `design-guard`, browser executor and project Storybook/type/quality commands | Existing toolchain reused; no mandatory replacement of project tooling |
| 35–37: layout/CLI | `quality/guards/design`, design-system, profiles; `design_guard.py`, `asset-prepare`, `svg-normalize` | Public CLI tests; documented project-relative output and source paths |
| 38–42, conclusion: workflow/priorities/anti-patterns | Plan → local checks → selected browser contract → inspect failure → accept baseline explicitly | No bulk CSS rewrite, all-Storybook prompt or automatic project restyling |

## 3 — Engineering Guard

| Sections | Implementation | Evidence / boundary |
| --- | --- | --- |
| 1–3: architecture/rules/security | Versioned check contracts, stack/risk route, scoped secret/Semgrep adapters | Missing tools and permission gaps never become passes; no runtime production security audit |
| 4–8: Next.js quality/architecture/performance | Next.js/HearthPulse profiles call types, lint, tests, architecture, Knip, audit and explicit heavy browser/bundle hooks | Existing HearthPulse commands retained; performance JSON compares real supplied metrics, not invented measurements |
| 9–13: Go | gofmt failure wrapper, vet, golangci-lint, focused tests, govulncheck, race and repeated benchmem | Optional tools must exist; `performance-check` evaluates exported comparable metrics; no deployed Go service changed |
| 14–19: PHP/WordPress standards/static analysis/architecture/security | WordPress preset: WPCS, PHPStan, dry-run Rector, Deptrac; real hs-manacost make targets and WP security module | No vendor/commercial-theme modifications; nonce/auth/SQL/escaping expectations remain scoped review rules |
| 20–21: WPScan/Composer | Composer audit and pinned WPScan disposable-stack command; separate public WPVulnerability adapter | Actual passive local scan passed; native advisory token unavailable. Public inventory lookup reports one core advisory/three unknown private plugins and fails honestly; no production scan |
| 22–23: tests/mutation | PHPUnit adapter and heavy single-worker Infection adapter; real project unit/integration commands | 22 PHPUnit scenarios; Infection 75.47% against 70% threshold; native integration passed |
| 24–26: WP performance/Query Monitor/rules | Existing project performance target; optional measurement contract + numeric budget evaluator; WP guard guidance | Actual local Query Monitor numeric export and four-screen/five-sample budget checks passed; diagnostic plugin deactivated and stack stopped |
| 27–30: clean code/architecture/dependencies/secrets | Project lint/architecture/Knip, Deptrac, audits and explicit-source Gitleaks | Full exact tool output stays private in reports; no global server scan |
| 31–33: budgets/failure/diff review | Finite metric validation, baseline comparison, ≤2000-token packet and report pointers | Tests cover missing/NaN/baseline/timeout/partial results; project metric thresholds are explicit config |
| 34–38: risk tiers/default gates/optional heavy tools | Fast/medium/heavy selection, sensitive paths raise risk, independent heavy/network flags | Routing/regression tests; project policies can demand additional checks and reviews |
| 39–42, conclusion: integration/unified command/order | `engineering-guard plan/verify`, `quality-plan/quality-verify`, real server profiles and canonical repository CI | Candidate source is in the actual skills repository supplying the installed tool; live activation not performed |

## 4 — Context Load Policy

| Sections | Implementation | Evidence / boundary |
| --- | --- | --- |
| 1–3: budgets/main rule/router | `quality/ROUTER.md` ≤1000 conservative estimated tokens; guard modules ≤1500; packet ≤12000 | Router/packet tests; CLI defaults to 8000 packet tokens, not an always-filled budget |
| 4–6: conditional token/design/engineering loading | `guard-context` selects 1–3 modules by changed paths, task and risk | Specialized assets/SVG/tokens/components/performance paths; multi-stack overload asks for a bounded phase |
| 7–9: selective verification/models/escalation | Check tiers and explicit permissions; local retrieval before evidence-gap providers | No model switch, all-checks run or paid call by default |
| 10–13: embeddings/rerank/GitHub/Context7 | Bounded providers, preview, source/model/version cache, reservations and limits | Backend cost ceiling is an operator contract/reservation, not an API billing guarantee |
| 14–16: design/failures/review | ≤3000-token design context, ≤2000-token diagnostics, selected sources/diff/artifacts | Exact files/logs remain addressable; mandatory instructions are not silently summarized away |
| 17–18: cache/resources | Hash/version caches, bounded retention, shared heavy/index lock and optional cgroup limits | Durable SQLite job queue: heavy=1/retrieval=2/remote=1, dedup/staleness/cancellation/orphan handling; independent custom roots remain separate domains |
| 19–21, conclusion: modules/hard rules/default | 16 on-demand modules and thin router; local deterministic defaults; optional expensive features | Server bootstrap/installed permanent entrypoints remain untouched pending review and activation authority |

Current per-section statuses and evidence are in `acceptance.json` (142 rows).
`completion.md` supersedes older application limitations and release evidence.
