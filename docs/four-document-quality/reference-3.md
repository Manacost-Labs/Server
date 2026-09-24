# Manacost Engineering Guard
## Security, Performance and Code Quality for Next.js, Go and PHP/WordPress

## Цель

Построить автоматический слой контроля качества, который:

- повышает безопасность кода;
- снижает количество архитектурных ошибок;
- ловит performance regressions;
- уменьшает technical debt;
- не требует постоянного LLM-review;
- возвращает Codex только конкретные ошибки и минимальный контекст.

Главный принцип:

> Всё, что можно проверить детерминированным инструментом, не нужно отдавать LLM.

---

# 1. Общая архитектура

```text
Codex implementation
        ↓
Formatter
        ↓
Lint
        ↓
Type / static analysis
        ↓
Architecture rules
        ↓
Security scan
        ↓
Tests
        ↓
Performance checks
        ↓
Dependency / vulnerability checks
        ↓
Only failures → Codex
```

---

# 2. Общие правила

Для всех стеков:

- минимальный scope изменений;
- запрет случайного рефакторинга;
- diff-oriented review;
- обязательные unit/regression tests для исправлений;
- architecture boundaries;
- dependency audit;
- secret scanning;
- performance budgets;
- автоматический rollback-safe verification;
- никакого full-repo LLM review без необходимости.

---

# 3. Security Layer

## Gitleaks

Поиск случайно закоммиченных:

- API keys;
- passwords;
- tokens;
- private keys;
- credentials.

GitHub:  
https://github.com/gitleaks/gitleaks

## Semgrep

Статический анализ:

- injection;
- unsafe APIs;
- insecure patterns;
- framework-specific mistakes.

GitHub:  
https://github.com/semgrep/semgrep

## Trivy

Проверка:

- dependencies;
- containers;
- filesystem;
- vulnerabilities;
- misconfigurations.

GitHub:  
https://github.com/aquasecurity/trivy

---

# 4. Next.js Engineering Guard

Pipeline:

```text
Biome / ESLint
↓
TypeScript strict
↓
tsc --noEmit
↓
Knip
↓
dependency boundaries
↓
Semgrep
↓
Vitest
↓
Playwright
↓
bundle analysis
↓
Web Vitals / performance budget
```

---

# 5. Next.js Code Quality

## ESLint

https://github.com/eslint/eslint

Использовать для:

- React rules;
- hooks;
- code smells;
- unsafe patterns.

## Biome

https://github.com/biomejs/biome

Использовать для:

- formatting;
- fast lint;
- import cleanup.

## TypeScript strict

Обязательно:

```json
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true
  }
}
```

## Knip

Ищет:

- unused files;
- unused exports;
- unused dependencies.

GitHub:  
https://github.com/webpro-nl/knip

---

# 6. Next.js Architecture Rules

Пример:

```text
UI
↓
application/services
↓
domain
↓
repositories
```

Запретить:

```text
UI → DB
UI → raw SQL
domain → Next.js runtime
client components → server-only modules
```

Для boundary rules можно использовать ESLint rules или собственный checker.

---

# 7. Next.js Performance Guard

Проверять:

```text
next build
bundle size
large client chunks
unnecessary client components
large images
slow API routes
LCP
CLS
INP
```

Полезно:

```text
@next/bundle-analyzer
Playwright
Lighthouse CI
```

Lighthouse CI:  
https://github.com/GoogleChrome/lighthouse-ci

---

# 8. Next.js Performance Budgets

Пример:

```text
JS bundle regression > 50 KB → fail
LCP regression > 10% → warning/fail
new image > allowed size → fail
unexpected client component → warning
```

Не использовать абсолютные лимиты слепо: baseline должен зависеть от проекта.

---

# 9. Go Engineering Guard

Pipeline:

```text
gofmt
↓
go vet
↓
golangci-lint
↓
Staticcheck
↓
gosec
↓
govulncheck
↓
go test ./...
↓
go test -race ./...
↓
benchmarks
↓
pprof / k6 when needed
```

---

# 10. Go Code Quality

## golangci-lint

GitHub:  
https://github.com/golangci/golangci-lint

Основной агрегатор линтеров.

## Staticcheck

GitHub:  
https://github.com/dominikh/go-tools

Ловит:

- incorrect API usage;
- dead code;
- suspicious constructs;
- performance issues.

---

# 11. Go Security

## gosec

GitHub:  
https://github.com/securego/gosec

## govulncheck

Официальная проверка vulnerable Go dependencies.

Дополнительно:

```text
Trivy
Semgrep
Gitleaks
```

---

# 12. Go Performance

Использовать:

```text
go test -bench
benchstat
pprof
race detector
k6
```

## pprof

https://github.com/google/pprof

## Go perf

https://github.com/golang/perf

## k6

https://github.com/grafana/k6

---

# 13. Go Performance Regression

Хранить baseline:

```text
BenchmarkX
allocs/op
B/op
ns/op
```

Новый PR сравнивается с baseline.

Пример:

```text
allocations +25% → fail
latency +15% → warning/fail
throughput -20% → fail
```

---

# 14. PHP / WordPress Engineering Guard

Pipeline:

```text
PHP-CS-Fixer / PHPCS
↓
WordPress Coding Standards
↓
PHPStan
↓
Rector dry-run
↓
Deptrac
↓
PHPUnit / Pest
↓
Semgrep
↓
Composer audit
↓
WPScan
↓
Query Monitor
↓
performance checks
```

---

# 15. WordPress Coding Standards

GitHub:  
https://github.com/WordPress/WordPress-Coding-Standards

Проверяет:

- WordPress style;
- escaping;
- sanitization;
- naming;
- common WP mistakes.

---

# 16. PHPStan

GitHub:  
https://github.com/phpstan/phpstan

Проверяет:

- types;
- null safety;
- incorrect calls;
- unreachable branches;
- invalid assumptions.

Рекомендуется постепенно повышать strictness.

---

# 17. Rector

GitHub:  
https://github.com/rectorphp/rector

Использовать для:

- safe modernization;
- repetitive refactors;
- PHP upgrades.

По умолчанию в CI:

```text
rector --dry-run
```

---

# 18. Deptrac

GitHub:  
https://github.com/qossmic/deptrac

Позволяет задать архитектуру:

```text
Presentation
↓
Application
↓
Domain
↓
Infrastructure
```

И запрещать:

```text
template → DB
controller → raw repository internals
domain → WordPress UI layer
```

---

# 19. WordPress Security Rules

Автоматически проверять:

```text
input sanitization
output escaping
nonce checks
capability checks
prepared SQL
REST permissions
file upload validation
CSRF protection
unsafe unserialize
direct DB access
```

Особенно:

```php
$wpdb->prepare()
```

для динамического SQL.

---

# 20. WPScan

GitHub:  
https://github.com/wpscanteam/wpscan

Использовать для:

- vulnerable plugins;
- vulnerable themes;
- WordPress core vulnerabilities.

---

# 21. Composer Audit

В CI:

```bash
composer audit
```

Проверять known vulnerabilities в PHP dependencies.

---

# 22. PHPUnit / Pest

PHPUnit:  
https://github.com/sebastianbergmann/phpunit

Pest:  
https://github.com/pestphp/pest

Использовать:

- unit tests;
- regression tests;
- service-layer tests;
- API tests.

---

# 23. Infection

GitHub:  
https://github.com/infection/infection

Mutation testing.

Полезно не на каждом commit, а:

```text
nightly
release
critical modules
```

---

# 24. WordPress Performance

Главные источники проблем:

```text
N+1 queries
WP_Query inside loops
uncached metadata
large autoloaded options
remote HTTP calls in request path
slow hooks
duplicate queries
heavy plugins
large frontend assets
```

---

# 25. Query Monitor

GitHub:  
https://github.com/johnbillion/query-monitor

Использовать для:

- slow queries;
- duplicate queries;
- hooks;
- HTTP requests;
- scripts/styles;
- REST calls.

---

# 26. WordPress Performance Rules

Запретить или сигнализировать:

```text
DB query inside render loop
uncached expensive queries
remote HTTP in page render
autoloaded huge options
unbounded WP_Query
SELECT *
missing pagination
missing object cache on hot paths
```

---

# 27. Clean Code Guard

Для всех языков измерять:

```text
cyclomatic complexity
function length
file length
dependency fan-out
duplicate code
dead code
unused exports
nested condition depth
```

Это не должно автоматически блокировать каждое превышение.

Использовать как:

```text
warning
→ repeated warning
→ fail threshold
```

---

# 28. Architecture Guard

Создать machine-readable policy.

Пример:

```yaml
layers:
  - ui
  - application
  - domain
  - infrastructure

rules:
  - ui -> application
  - application -> domain
  - infrastructure -> domain
```

Запрещённые зависимости автоматически проверяются.

---

# 29. Dependency Guard

Перед добавлением новой dependency проверять:

```text
есть ли уже аналог в проекте
maintenance status
license
size
security history
last release
transitive dependencies
```

Codex не должен автоматически добавлять пакет только потому, что он удобный.

---

# 30. Secret Guard

Проверять:

```text
pre-commit
CI
release
```

Минимум:

```text
Gitleaks
```

Никогда не отдавать найденный секрет целиком обратно в LLM.

---

# 31. Performance Budget

Для каждого проекта хранить:

```yaml
frontend:
  bundle_regression_percent: 10
  lcp_regression_percent: 10

api:
  p95_regression_percent: 15

go:
  allocations_regression_percent: 20

wordpress:
  max_duplicate_queries: 0
  max_slow_query_ms: 100
```

Значения нужно настроить после baseline.

---

# 32. Failure Packet

LLM не получает полный лог.

Система формирует:

```text
check
file
line
error
related symbol
small diff
relevant test
```

Пример:

```text
Check: PHPStan
File: src/Auth/LoginService.php
Line: 84
Error: nullable value passed to non-null parameter

Relevant diff:
...

Related test:
LoginServiceTest::testInvalidUser
```

---

# 33. Diff-only Review

Review получает:

```text
task
acceptance criteria
architecture constraints
git diff
failed/passed checks
performance deltas
security findings
```

Не весь репозиторий.

---

# 34. Risk-based Verification

## LOW

```text
format
lint
typecheck
focused tests
```

## MEDIUM

```text
+ static analysis
+ relevant security checks
+ integration tests
```

## HIGH

```text
+ full relevant suite
+ security
+ performance
+ independent review
```

## CRITICAL

```text
+ rollback test
+ migration safety
+ full security gate
+ senior review
```

---

# 35. Next.js Default Gate

```text
biome/eslint
tsc --noEmit
knip
semgrep
unit tests
playwright
bundle budget
lighthouse where relevant
```

---

# 36. Go Default Gate

```text
gofmt
go vet
golangci-lint
staticcheck
gosec
govulncheck
go test
race detector where relevant
benchmarks on hot paths
```

---

# 37. PHP / WordPress Default Gate

```text
PHPCS + WPCS
PHPStan
Rector dry-run
Deptrac
PHPUnit/Pest
Semgrep
composer audit
WPScan
Query Monitor/performance checks
```

---

# 38. Что запускать не всегда

Тяжёлые проверки не нужно запускать на каждом маленьком изменении.

Например:

```text
Infection
full Playwright suite
full benchmarks
k6 load tests
WPScan full scan
Trivy full image scan
```

Можно запускать:

```text
nightly
release
high-risk changes
dependency changes
```

---

# 39. Integration with Manacost-Labs/Server

Добавить:

```text
quality-gates/
├── shared/
│   ├── security
│   ├── architecture
│   ├── dependencies
│   └── secrets
│
├── nextjs/
│   ├── lint
│   ├── types
│   ├── tests
│   └── performance
│
├── go/
│   ├── lint
│   ├── security
│   ├── tests
│   └── benchmarks
│
└── wordpress/
    ├── wpcs
    ├── phpstan
    ├── deptrac
    ├── security
    ├── tests
    └── performance
```

---

# 40. Единая команда

```bash
engineering-guard verify
```

Опции:

```bash
engineering-guard verify --stack nextjs
engineering-guard verify --stack go
engineering-guard verify --stack wordpress
```

И режим:

```bash
engineering-guard verify --risk low
engineering-guard verify --risk medium
engineering-guard verify --risk high
```

---

# 41. Итоговая система Manacost

```text
Context Economy
→ меньше токенов

Design Guard
→ единый качественный UI

Engineering Guard
→ безопасность
→ производительность
→ чистый код
→ архитектурная дисциплина
```

---

# 42. Рекомендуемый порядок внедрения

## P0

1. Gitleaks
2. Semgrep
3. Next.js strict TypeScript
4. golangci-lint + Staticcheck
5. PHPStan + WPCS
6. unit/regression tests
7. architecture boundaries
8. diff-only failure packets

## P1

9. Trivy
10. gosec + govulncheck
11. Deptrac
12. bundle/performance budgets
13. Query Monitor
14. Composer audit / WPScan

## P2

15. benchmark regression system
16. k6
17. Infection
18. advanced dependency scoring
19. automated architecture graph
20. project-specific performance baselines

---

# Итог

Для качественного AI-кода не нужно постоянно запускать более дорогую модель.

Лучший подход:

```text
Codex пишет код
↓
детерминированные инструменты проверяют
↓
система формирует маленький failure packet
↓
Codex исправляет только конкретную проблему
```

Так одновременно:

- повышается безопасность;
- уменьшаются regressions;
- код остаётся чище;
- производительность контролируется автоматически;
- Codex тратит меньше токенов;
- review становится точнее.
