# HearthPulse and hs-manacost.ru

The user selected both projects. Bundled profiles connect the shared commands to
their actual source paths and existing checks. This is a server-tool integration;
application source, CI configuration, production UI and runtime were not changed.

## HearthPulse

Source: `/srv/projects/web/arena.hs-manacost.ru` (HearthPulse/hearthpulse.net).
Profile: `quality/profiles/hearthpulse.json`.

- Canonical tokens: `src/styles/tokens.css` — 33 declarations validated.
- Registry: HeaderProfileButton (with its story), SubscriptionPurchaseButtons,
  ConstructedCardDownloadButton — three source components validated.
- Engineering: existing `lint`, `lint:next`, `test:registry`,
  `lint:architecture`, `security:semgrep`, `quality:knip` npm scripts.
- Design: token/component validation; selected Storybook tests/build at higher tiers.

The task worktree `/srv/projects/tasks/hearthpulse-four-document-quality-20260923`
was created without application edits. Its required preflight reports HEAD
`2c6977b00755` **130 commits ahead and one behind**
origin/main `28a469707fd3`.
The agent-context command also lacks local TypeScript dependencies in that fresh
worktree. Logs: `/tmp/hearthpulse-quality-preflight.log`,
`/tmp/hearthpulse-quality-context.log`.
Do not merge/rebase those unrelated commits to hide the preflight failure.
Resolve the intended application base before adopting shared primitives or
modifying the application's CI. Read-only profile validation can proceed now.

## hs-manacost.ru

Canonical source: `/srv/projects/wordpress/hs-manacost.ru`, baseline
`487d9394` (detached checkout). Profile: `quality/profiles/hs-manacost.json`.

- Canonical Reader tokens: `wordpress/mu-plugins/hs-manacost-reader/ui.css`
  and `reader.css` — 32 declarations validated, scoped to `.mc-reader-ui`.
- Registry: ReaderButton, ReaderAccount, ReaderComments, PlatformIcons — four
  first-party components validated.
- Engineering: existing `make php-lint`, `contract-check`, `test`, `code-quality`,
  `reader-css-check`, `reader-test`; explicit heavy integration/visual targets.
- The existing project contract and WordPress hooks/security rules remain authoritative.

The commercial Newspaper_new theme, Reader theme overrides and the independent
Next.js web-v2 sandbox are not forcibly converted to one new palette. Runtime
`/var/www/koloda/data/www/hs-manacost.ru`, secrets and existing integration volumes
were not modified. Heavy project integration uses its Docker harness; its network
and container lifecycle need explicit selection and existing project safeguards.

## Use the candidate profiles

```sh
quality_src=/srv/projects/tools/skills-four-document-quality-candidate-20260923/integrations/codex/subscription-savings
quality_python=/tmp/four-document-quality-venv-20260923/bin/python
"$quality_python" "$quality_src/design_guard.py" --project /srv/projects/web/arena.hs-manacost.ru --profile hearthpulse verify --changed src/styles/tokens.css --task-type ui
"$quality_python" "$quality_src/design_guard.py" --project /srv/projects/wordpress/hs-manacost.ru --profile hs-manacost verify --changed wordpress/mu-plugins/hs-manacost-reader/ui.css --task-type ui
"$quality_python" "$quality_src/engineering_guard.py" --project /srv/projects/wordpress/hs-manacost.ru --profile hs-manacost plan --changed wordpress/mu-plugins/hs-manacost-reader/account.php --risk medium
```

The first two commands passed against real source during this task. This proves
the token/registry profiles work; it does not claim the full applications passed
their engineering, browser, security or performance suites. Per-application CI
adoption and UI changes remain visible follow-up work after the application base
and activation/review gates are satisfied.

## Activation and rollback gate

Current installed release stays
`/home/debian/.local/share/codex-context-economy/releases/2026-09-22-quality-v2-07ca752`.
Its `current` link and installed launchers were not changed. Candidate source is
on `codex/four-document-quality-candidate-20260923`, based on
`07ca7523660e`, with uncommitted owned changes.

Before activation:

1. Complete the repository's required independent HIGH-risk review against the
   candidate diff and verification. No automatic senior-model call is authorized.
2. Obtain explicit authority for the live installation. Root project AGENTS.md
   requires it; preparing source and testing does not authorize deployment.
3. Build a **new** release from this source with `requirements-quality.txt`,
   locked npm dependencies and a dedicated venv; preserve all existing modules
   and wrappers. Record base commit plus the candidate's file-hash manifest.
   Dirty candidate source must not be labeled as the clean base commit.
4. Smoke-test that new release by absolute path (CLI, profiles and local fixture),
   then switch launchers/current together. The old context-economy launcher uses
   `/usr/bin/python3`; it must use the new release venv for optional quality deps.
   New engineering/design wrappers select a release `.venv` when present.
5. Add only the small router or an on-demand pointer to the approved agent
   entrypoint; do not paste four documents or 16 modules into permanent context.
6. Roll back by restoring the previous launcher contents and `current` target.
   Keep the previous release and backups; never delete state, sessions or volumes.

This task prepares the source and review evidence. It does not execute these
activation steps, change model defaults or grant production-test permission.
