# Commands and contracts

Run from the candidate checkout. Dependencies are installed in an isolated
environment; installing them does not activate the candidate on the server:

```sh
quality_src="$PWD/integrations/codex/subscription-savings"
python3 -m venv "$quality_src/.venv"
"$quality_src/.venv/bin/pip" install -r "$quality_src/requirements-quality.txt"
npm ci --ignore-scripts --no-audit --no-fund --prefix "$quality_src/quality"
export PATH="$quality_src/.venv/bin:$quality_src/quality/node_modules/.bin:$PATH"
```

Use a Python/Pillow platform with AVIF and WebP support. The test installation on
this host is `/tmp/four-document-quality-venv-20260923`, not a global pip install.
Browser execution needs either a provisioned Chromium via
`QUALITY_CHROMIUM_EXECUTABLE`, or the pinned Playwright browser:

```sh
"$quality_src/quality/node_modules/.bin/playwright" install chromium
```

The CI workflow installs these dependencies and executes the same `make verify`.
The generic quality profiles do not install application dependencies or tools.
`ctx7`, `gh`, Gitleaks, Semgrep, Go tools and PHP/Node project tools are explicit
prerequisites for the respective optional commands. A missing tool fails the gate.

## Retrieve and verify code context

All source paths are relative to the selected project, not the tooling checkout.
Use concrete source/test paths; `--source .`, protected paths and symlinks are rejected.
`repo-map --source PATH --budget 3000` returns a compact index summary with explicit
omission counts; its full local AST cache is not dumped into the conversation.

```sh
python "$quality_src/context_economy.py" --project /path/to/project search 'cache expiry' --source src/cache --source tests/cache
python "$quality_src/context_economy.py" --project /path/to/project symbols Cache --source src/cache
python "$quality_src/context_economy.py" --project /path/to/project callers Cache --source src/cache --source tests/cache
python "$quality_src/context_economy.py" --project /path/to/project tests Cache --source tests/cache
python "$quality_src/context_economy.py" --project /path/to/project context-build --task task.json --source src/cache --source tests/cache --required AGENTS.md --symbol Cache --budget 8000 > /path/to/project/context.json
python "$quality_src/context_economy.py" --project /path/to/project verify-context context.json --budget 8000
```

`task.json` has `goal` (string), `criteria` (string array) and `constraints` (string
array). Include the applicable policy and any verified ADR as required sources.
The builder packs local definitions/callers/test candidates and lexical excerpts.
It does not automatically consult memory, download docs or upload source. Use
existing `recall`/`inspect` for evidence-backed memory, and `pack` for explicit
additional sources. Mandatory content must fit; it is never silently dropped.

The new commands supplement existing `focus`, `brief`, `read`, `gate`, `remember`,
`meter-*`, `pilot-*` and `benchmark.py`. Meter reports distinguish estimates,
recorded provider usage, cache hits and measured task/session usage. Compare
matched real tasks and quality outcomes; toy fixture reductions are not savings.

## Plan and run checks

```sh
python "$quality_src/context_economy.py" guard-context --changed src/auth.ts --risk low
python "$quality_src/engineering_guard.py" --project /path/to/project --profile nextjs plan --changed src/cache.ts --risk medium
python "$quality_src/engineering_guard.py" --project /path/to/project --profile nextjs verify --changed src/cache.ts --risk medium
```

Sensitive paths raise the inferred risk. `plan` executes no checks. Medium/heavy
checks depend on risk/task triggers. `--allow-heavy` and `--allow-network` are
separate explicit opt-ins; neither is inferred from a profile. `--only CHECK`
leaves other required selected checks NOT_RUN, making the result incomplete.
Reports distinguish failed, timed_out, missing_tool, blocked and not_applicable.

A project can own `.ai/manacost-quality.json` instead of choosing a bundled profile:

```json
{
  "version": 1,
  "stack": "nextjs",
  "heavy_limits": {"cpu_percent": 200, "memory_mb": 2048},
  "checks": [
    {"id": "types", "argv": ["npm", "run", "typecheck"], "tier": "fast"},
    {"id": "browser", "argv": ["npm", "run", "test:e2e"], "tier": "heavy", "timeout": 600}
  ]
}
```

Checks use argv arrays, not shell strings. Optional fields: `family` (engineering
or design), `paths` (globs), `required` (defaults true), `network`, `timeout`.
Placeholders are `{python}`, `{quality_root}`, `{changed}`, `{changed_php}`,
`{changed_js}`, `{changed_go}`, `{go_packages}`. Source file placeholders expand
to individual arguments. Relative executables resolve inside the project.
Use pass caching only with `cache: true`, `complete_inputs: true` and explicit
`inputs` covering configs, lockfiles, tool versions and all relevant sources.
Generic/default project checks deliberately do not cache unverifiable test passes.

Heavy limits require a functioning systemd user manager. Failure to create its
scope is a failed/blocked check, not unlimited fallback. Docker daemon children
need limits in the project's Compose/container configuration too; a client scope
cannot enforce the daemon's container memory. Different custom `--state-dir`
roots do not share the default resource lock.

## Design contracts, browser and assets

The design section of the project config can use a JSON token file or
`"tokens": {"from_css": ["src/styles/tokens.css"]}`. Set `token_sources` and
`token_selectors` to canonical declarations; theme overrides are not silently
flattened into the universal palette. A JSON token file is `{"tokens": {...}}`.
`registry` is either a local JSON file with a `components` array or that array
inline. Each component has `name`, `source`, optional `tokens`, `stories`,
`states`, `screenshots`, `asset_preset`, and `responsive_rules`.

```sh
python "$quality_src/design_guard.py" --project /path/to/project tokens
python "$quality_src/design_guard.py" --project /path/to/project css --source src/card.css
python "$quality_src/design_guard.py" --project /path/to/project context --query 'article card'
python "$quality_src/context_economy.py" --project /path/to/project svg-normalize icons/source.svg --output icons/normalized.svg --monochrome
python "$quality_src/context_economy.py" --project /path/to/project asset-prepare art/source.png --preset hero-art --output public/art/hero-v1 --alt 'A mage overlooking the arena'
```

Asset presets: hero-art, character-cutout, card-background, portrait,
decorative-overlay. Supply `--decorative` for non-informative images. Explicit
`--focal-x` and `--focal-y` override the edge-saliency heuristic. Background removal
requires explicit `--remove-background` and a separately provisioned rembg model.
Existing output paths are refused; source images and SVGs are immutable.
The shared component and CSS live in `quality/design-system/`.

Minimal browser contract `.ai/quality-browser.json`:

```json
{
  "version": 1,
  "widths": [375, 768, 1024, 1440],
  "pages": [{
    "id": "card", "path": "/quality-fixture", "ready": "#save",
    "computed": [{"selector": "#save", "property": "height", "equals": "44px"}],
    "keyboardOrder": ["#save"]
  }],
  "pixelThreshold": 0.1,
  "maxChangedPixelRatio": 0.001
}
```

```sh
node "$quality_src/quality/browser.mjs" --project /path/to/project --base-url http://127.0.0.1:3000
```

Missing baseline fails. Inspect the generated screenshot, then explicitly use
`--update-baselines` to accept it. Keep browser version, fonts and rendering OS
comparable; the report records browser version. Nonlocal targets require
`--allow-remote-target`; it is not authority to test production. Optional
`allowedResourceOrigins` permits named asset origins. Artifacts default to
`.ai/quality-artifacts/run-*`, baselines to `.ai/visual-baselines`. Keep temporary
artifacts out of commits. No screenshot corpus is loaded into a prompt.

`performance-check --current measurements.json --baseline baseline.json
--budgets budgets.json` accepts numeric metrics and per-metric `maximum` and/or
`regression_percent`. Missing/nonfinite evidence fails. Collect repeated comparable
Lighthouse/benchstat/WordPress reports first; this evaluator is not a statistical test.

## Optional providers

Native OpenRouter defaults and actual working examples are documented in
[Real code and OpenRouter](retrieval-openrouter.md). `semantic-search` and
`rerank` now work with the existing private server credential without a custom
provider subprocess. `reference-search --rerank-references` reranks verified
GitHub implementations; `--include-tests` explicitly includes test sources.
The native adapter uses a tighter 24 KB payload limit and the shared server ledger.
The following subprocess contract remains available for explicit custom providers.

`docs`, `reference-search`, `semantic-search` and `rerank` require a bounded query
and `--evidence-gap`. Inspect `--preview-remote` first; cache misses require
`--allow-remote`. `docs` additionally needs `--library` and `--library-version`.
Query text/source is sent only on the explicitly selected provider operation.

For semantic providers, configure `providers.semantic-search` or `providers.rerank`
with an absolute `argv` array, immutable `revision`, `network`, `calls_per_day`.
Remote backends also require `max_cost_usd` (0–1, positive) and `daily_budget_usd`.
The backend reads one JSON object from stdin and emits one JSON object. Input
contains `operation`, `query`, `revision`, `max_results` and bounded `candidates`
with `id`, `source`, `sha256`, `text`. Reranker response must return every supplied
ID exactly once with a finite `score`. Embeddings response returns
`query_embedding` and each candidate's `embedding`; cached chunks are omitted
from later requests, so an empty candidates array is valid. Return optional
actual `usage`; never invent it. Model/backend revision changes invalidate cache.

At most 30 candidates/64 KB enter a provider; results are limited to 5 (semantic)
or 3 (docs/GitHub). Daily calls/cost ceilings are reserved even if a call fails.
The adapter reserves a declared ceiling; only the backend/provider can enforce
actual billing. Native OpenRouter reuses the existing server credential; bounded
live validation and reported costs are recorded in `retrieval-openrouter.md`.
No new API key or local heavy model was provisioned.

WPScan, Query Monitor and application performance collectors are optional
project operations. To add a scanner, configure an explicit argv/check and an
authorized target, mark network/heavy accurately, and keep it out of default
fast gates. Never infer the production URL from the project name.
