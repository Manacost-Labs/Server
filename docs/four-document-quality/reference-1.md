# Manacost-Labs/Server: Token Economy + Code Quality

## Цель

Построить для Codex инфраструктуру, которая одновременно:

- уменьшает расход контекста и токенов;
- повышает качество генерируемого кода;
- снижает число повторных проходов Codex;
- минимально нагружает сервер;
- использует дешёвые модели только там, где они реально полезны;
- максимально заменяет LLM-проверки детерминированными инструментами.

Основной принцип:

> Codex не должен читать весь проект, всю документацию и десятки GitHub-репозиториев. Он должен получать только минимальный проверенный контекст, необходимый для конкретной задачи.

---

## 1. Что уже есть в Manacost-Labs/Server

В репозитории уже реализована хорошая база:

- `context-economy`;
- ограничение context budget;
- JEV для advisory/model routing;
- Gemma для дешёвого сжатия контекста;
- `ai-memory`;
- кэширование;
- `focus.py` для bounded поиска;
- `packing.py` для сборки контекстного пакета;
- `briefs.py` для кратких справок;
- benchmark реального расхода токенов;
- diff-oriented workflow;
- scoped skills;
- ограничение количества загружаемых skills;
- project/worktree isolation;
- quality gates и verification policy.

Главная следующая задача — улучшить retrieval: искать правильный код, символы, тесты, документацию и хорошие внешние реализации до того, как задача попадёт в Codex.

---

# 2. Итоговая архитектура

```text
User task
   ↓
Cheap task classifier / JEV
   ↓
Task normalization
   ↓
┌───────────────────────────────────┐
│          Retrieval Layer          │
│                                   │
│  1. Project memory                │
│  2. Repo map / symbols            │
│  3. AST / call graph              │
│  4. Related tests                 │
│  5. Context7 documentation        │
│  6. External GitHub patterns      │
└───────────────────────────────────┘
   ↓
Hybrid ranking
   ↓
Optional cheap reranker
   ↓
Context pack: ~8–15k useful tokens
   ↓
Codex implementation
   ↓
Deterministic quality gates
   ↓
Only failures + diff → Codex
   ↓
Focused review
```

---

# 3. Этап 1 — дешёвая классификация задачи

Использовать JEV или другую очень дешёвую модель только для определения:

- типа задачи;
- языка;
- framework;
- компонентов проекта;
- риска;
- необходимых источников;
- поисковых ключей.

Пример:

```text
"сделай хороший кеш для API"
```

Преобразуется в:

```json
{
  "task": "api_cache",
  "language": "go",
  "patterns": [
    "redis",
    "cache-aside",
    "ttl",
    "singleflight"
  ],
  "needs_docs": true,
  "needs_external_examples": true
}
```

JEV не пишет код. Он только дешёво подготавливает retrieval.

---

# 4. Repo Map вместо чтения проекта

Codex не должен начинать задачу с чтения десятков файлов.

Нужно построить компактный индекс:

```text
file
symbol
type
imports
exports
callers
callees
tests
dependencies
```

Инструменты:

- Tree-sitter  
  https://github.com/tree-sitter/tree-sitter
- SCIP  
  https://github.com/sourcegraph/scip
- ast-grep  
  https://github.com/ast-grep/ast-grep

Пример:

```text
CreateSession
├── defined: internal/auth/session.go
├── callers:
│   ├── handlers/login.go
│   └── oauth/callback.go
├── dependencies:
│   ├── SessionRepository
│   └── TokenService
└── tests:
    └── session_test.go
```

Это намного дешевле, чем давать Codex весь модуль.

---

# 5. Заменить regex symbol search на AST search

Сейчас часть bounded retrieval в `focus.py` основана на текстовом/regex поиске.

Для простых случаев это нормально, но для сложного кода лучше:

```text
AST → symbol → references → tests
```

Это уменьшает:

- ложные совпадения;
- чтение нерелевантных файлов;
- потерю реальных зависимостей;
- количество токенов.

Приоритет: высокий.

---

# 6. Быстрый локальный code search

Для текстового поиска использовать:

### Zoekt

https://github.com/sourcegraph/zoekt

Подходит для:

- имен функций;
- ошибок;
- imports;
- config keys;
- API names;
- точных паттернов.

Схема:

```text
AST search → структурные связи
Zoekt → быстрый lexical search
```

Не нужно использовать embeddings для каждого запроса.

---

# 7. Поиск связанных тестов автоматически

Перед изменением функции система должна искать:

```text
symbol
→ callers
→ implementation
→ unit tests
→ integration tests
```

Codex получает тесты до написания кода.

Это позволяет модели понять фактическое ожидаемое поведение без чтения всего проекта.

Преимущества:

- меньше регрессий;
- меньше повторных исправлений;
- меньше review-токенов;
- выше шанс написать правильный код с первого раза.

---

# 8. Context7 для актуальной документации

Context7:

https://github.com/upstash/context7

Использовать только когда задача зависит от внешнего API:

```text
Next.js
React
Supabase
Cloudflare
Stripe
Redis client
ORM
framework/library APIs
```

Не передавать Codex всю документацию.

Пример:

```text
Task:
Next.js middleware authentication

Context7:
→ Next.js current middleware docs
→ NextRequest
→ cookies
→ relevant example
```

В контекст отправляется только нужный фрагмент.

---

# 9. External Reference Search

Добавить новую функцию:

```bash
context-economy reference-search \
  "Next.js Redis rate limiter"
```

Она должна искать хорошие реализации в open-source коде.

Система не должна отправлять Codex 20 репозиториев.

Она должна вернуть:

```text
Pattern: Redis rate limiter

Reference 1
repo: ...
file: ...
lines: 20-85

Reference 2
repo: ...
file: ...
lines: 40-110

Important concepts:
- atomic increment
- TTL
- race safety
- fallback behavior
```

Codex получает 2–3 лучших реализации.

---

# 10. Как определять хороший GitHub-код

Первичный score можно считать вообще без LLM:

```text
repository activity
tests present
CI present
license
recent commits
stars
maintainers
type safety
documentation
dependency freshness
archived/not archived
```

Дополнительно:

```text
+ official repository
+ tests around the target implementation
+ used in production project
- stale repository
- no tests
- huge unstructured function
- deprecated API
```

LLM не нужен для первичной фильтрации.

---

# 11. Embeddings — только когда lexical/AST поиска недостаточно

Не стоит делать embeddings главным поисковиком.

Порядок:

```text
1. Symbol/AST search
2. Zoekt/BM25
3. Embeddings fallback
```

Embeddings полезны для запросов типа:

```text
"защита от повторной отправки формы"
```

когда в коде это может называться:

```text
idempotency
request deduplication
nonce
submission guard
```

Embedding должен работать только на уже ограниченном наборе документов.

---

# 12. Reranker

Reranker получает, например:

```text
30 найденных fragments
```

и оставляет:

```text
TOP 3–5
```

Codex не видит остальные.

Именно это позволяет увеличить качество контекста без увеличения его размера.

Схема:

```text
Zoekt/AST/embedding
      ↓
30 candidates
      ↓
reranker
      ↓
5 candidates
      ↓
context pack
```

Reranker можно вынести в дешёвый API, чтобы не грузить сервер.

---

# 13. Кэшировать embeddings и retrieval

Embedding кода не нужно считать каждый раз.

```text
file SHA
↓
embedding
↓
cache
```

Если файл не изменился — embedding повторно не считается.

Также кэшировать:

```text
query
framework version
repository version
retrieved references
```

Пример:

```text
Next.js + Better Auth + Google OAuth
```

один раз качественно найдено → используется повторно до изменения версии.

---

# 14. Reference Pattern Cache

Хранить проверенные решения:

```text
patterns/
├── nextjs/
│   ├── auth
│   ├── middleware
│   ├── uploads
│   └── rate-limit
├── go/
│   ├── cache
│   ├── worker-pool
│   ├── graceful-shutdown
│   └── idempotency
└── shared/
    ├── oauth
    ├── webhooks
    └── pagination
```

Pattern содержит не копию целого проекта, а:

```text
problem
recommended approach
known traps
reference repositories
important files
tests
license
framework/version
```

Это снижает повторный research.

---

# 15. Architecture Memory

Codex не должен каждый раз выяснять архитектуру проекта.

Для каждого проекта хранить краткую карту:

```yaml
frontend: Next.js
backend: Go
database: PostgreSQL
cache: Redis
auth: Better Auth
api: REST
ui: shadcn
tests:
  frontend: Vitest + Playwright
  backend: go test
```

Дополнительно:

```text
important modules
ownership boundaries
public APIs
protected paths
architectural decisions
```

Размер — условно 500–1500 токенов.

---

# 16. Context Packing

Существующий `packing.py` сохранить, но перед ним добавить ranking.

Пример бюджета:

```text
Task/constraints        1k
Architecture            1k
Target implementation   3k
Dependencies            2k
Tests                   2k
Documentation           2k
External references     3k
Memory                  1k
---------------------------
Total                  ~15k
```

Если context больше бюджета:

```text
не truncate случайно
→ rerank
→ убрать слабейшие candidates
```

---

# 17. Diff-only workflow

После первого изменения не нужно снова передавать весь контекст.

Следующий проход:

```text
task
+ decisions
+ changed symbols
+ git diff
+ failed tests
```

Это особенно сильно экономит токены на циклах исправления.

---

# 18. Детерминированные проверки вместо LLM

LLM не должен искать ошибки, которые умеет находить compiler/linter.

## Next.js

Рекомендуемый pipeline:

```text
Biome / ESLint
↓
TypeScript strict
↓
tsc --noEmit
↓
Knip
↓
Vitest
↓
Playwright
↓
Semgrep
```

GitHub:

- ESLint  
  https://github.com/eslint/eslint
- Biome  
  https://github.com/biomejs/biome
- Knip  
  https://github.com/webpro-nl/knip
- Vitest  
  https://github.com/vitest-dev/vitest
- Playwright  
  https://github.com/microsoft/playwright
- Semgrep  
  https://github.com/semgrep/semgrep

---

# 19. Go quality pipeline

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
```

GitHub:

- golangci-lint  
  https://github.com/golangci/golangci-lint
- Staticcheck / go-tools  
  https://github.com/dominikh/go-tools
- gosec  
  https://github.com/securego/gosec

---

# 20. Возвращать Codex только ошибки

Плохо:

```text
"перепроверь весь проект"
```

Хорошо:

```text
go test failed:

internal/auth/session_test.go:84

Expected:
401

Received:
500

Related symbol:
CreateSession

Relevant diff:
...
```

Codex получает только минимальный diagnostic context.

---

# 21. Security без LLM

Автоматически запускать:

```text
Semgrep
gosec
govulncheck
dependency audit
secret scanning
```

LLM подключается только если scanner нашёл проблему, которую нужно исправить.

---

# 22. Complexity / maintainability gate

Можно ввести простые правила:

```text
max function complexity
max function length
max file size
max dependency fan-out
duplicate code detection
```

Не запрещать сложность механически, а использовать как сигнал.

Codex получает предупреждение только при превышении разумного порога.

---

# 23. Review должен получать diff, а не repository

Reviewer:

```text
task
architecture summary
important contracts
diff
tests
scanner results
```

Не:

```text
entire repository
```

Для большинства задач этого достаточно.

---

# 24. Когда использовать более сильную модель

Не использовать Sol/Astra автоматически на каждом этапе.

Пример:

```text
mechanical change
→ deterministic tools

simple bounded implementation
→ Terra/Luna-level worker

normal implementation
→ Sol

architecture/security/root cause
→ senior model/review
```

JEV может давать advisory, но окончательная policy остаётся в Server.

---

# 25. Серверная нагрузка

Для сервера:

```text
8-core Ryzen
~20 GB free RAM
```

локально оставить:

```text
Zoekt
Tree-sitter
SCIP index
SQLite/PostgreSQL
repo cache
context-economy
ai-memory
quality gates
```

Не стоит держать несколько тяжёлых embedding/reranker моделей одновременно.

Embeddings/reranking лучше:

```text
API
или
очень маленькая локальная модель + очередь
```

---

# 26. Защита сервера от параллельной нагрузки

Добавить worker queue:

```text
retrieval workers: 2–4
embedding concurrency: 2
reranker concurrency: 2
indexing: low priority
```

Ограничения:

```text
CPU quota
memory limit
timeouts
queue length
```

Индексацию выполнять инкрементально:

```text
git diff
→ changed files only
→ update AST
→ update symbols
→ update embeddings
```

Не переиндексировать репозиторий целиком после каждого commit.

---

# 27. Что даст наибольший эффект

Приоритет:

## P0

1. AST / symbol retrieval
2. related test retrieval
3. deterministic Next.js/Go quality gates
4. diff-only correction loops
5. retrieval cache

## P1

6. Context7
7. external GitHub reference search
8. reference pattern cache
9. reranker

## P2

10. embeddings fallback
11. advanced call graph
12. cross-project pattern knowledge base

---

# 28. Что не стоит делать

Не нужно:

- отправлять весь repository в embeddings;
- использовать LLM для lint;
- использовать LLM для обычного typecheck;
- делать reranking сотен файлов;
- автоматически читать десятки GitHub repos;
- запускать сильную модель ради простого поиска;
- каждый раз пересчитывать embeddings;
- передавать reviewer весь проект;
- хранить длинные разговоры как memory;
- строить огромный vector DB раньше, чем будет доказана его польза.

---

# 29. Предлагаемые новые команды context-economy

```bash
context-economy symbols <symbol>

context-economy callers <symbol>

context-economy tests <symbol>

context-economy docs \
  --library nextjs \
  --query "middleware authentication"

context-economy reference-search \
  "Go Redis cache singleflight"

context-economy context-build \
  --task task.json \
  --budget 12000

context-economy verify-context \
  context.json
```

---

# 30. Новый Context Builder

Главная команда:

```text
context-build(task)
```

делает:

```text
1. classify task
2. read architecture memory
3. find target symbols
4. find callers/dependencies
5. find related tests
6. query docs if required
7. query external patterns if useful
8. rerank
9. deduplicate
10. enforce budget
11. produce final context packet
```

Codex получает уже готовый пакет.

---

# 31. Expected pipeline для Next.js

```text
Feature request
↓
JEV classification
↓
project architecture
↓
TS/AST symbol search
↓
related components/hooks/tests
↓
Context7 Next.js docs
↓
GitHub reference patterns
↓
reranker
↓
Codex
↓
tsc
↓
Biome/ESLint
↓
Knip
↓
Vitest
↓
Playwright
↓
Semgrep
↓
failures only → Codex
```

---

# 32. Expected pipeline для Go

```text
Feature request
↓
JEV classification
↓
project architecture
↓
Go symbol/call graph
↓
related interfaces/tests
↓
Context7/docs if needed
↓
GitHub implementation patterns
↓
reranker
↓
Codex
↓
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
go test
↓
race detector
↓
failures only → Codex
```

---

# 33. Почему качество вырастет

Codex получает:

```text
не больше информации
```

а:

```text
более правильную информацию
```

Вместо:

```text
50 случайных файлов
```

получает:

```text
target function
3 dependencies
2 tests
актуальную документацию
2 качественных reference patterns
```

Это уменьшает вероятность:

- неправильной архитектуры;
- устаревшего API;
- дублирования существующей логики;
- несовместимости с проектом;
- отсутствия тестов;
- лишнего кода;
- security regressions.

---

# 34. Почему расход токенов уменьшится

Основные источники экономии:

```text
repo map вместо чтения repo
AST вместо grep + чтения файлов
test retrieval вместо exploration
Context7 вместо чтения docs целиком
reference search вместо GitHub research агентом
reranker вместо передачи TOP-30
cache вместо повторных запросов
diff-only вместо полного повторного контекста
linters вместо LLM review
```

На research-heavy задачах разумная цель:

```text
−30–60% входного контекста Codex
```

Но это нужно подтверждать существующим benchmark в `Server`, а не считать гарантированной цифрой.

---

# 35. Метрики

Для каждой задачи измерять:

```text
Codex input tokens
Codex output tokens
helper API cost
time
retries
reworks
tests passed
quality gate failures
context size
retrieved candidates
selected candidates
cache hit rate
```

Дополнительные retrieval metrics:

```text
precision@5
test retrieval hit rate
symbol retrieval hit rate
external reference usage rate
```

Главная метрика:

```text
меньше токенов
при том же или более высоком acceptance rate
и без роста rework
```

---

# 36. Рекомендуемый MVP

Не строить всё сразу.

## Phase 1

```text
Tree-sitter
+
Zoekt
+
automatic related tests
+
Next.js/Go quality gates
```

## Phase 2

```text
Context7
+
external GitHub reference-search
+
reference cache
```

## Phase 3

```text
reranker
+
optional embeddings
+
advanced symbol/call graph
```

---

# 37. Финальная рекомендуемая система

```text
                    ┌──────────────┐
                    │ User request │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ JEV / router │
                    └──────┬───────┘
                           ↓
                 ┌─────────────────────┐
                 │ Retrieval Orchestrator│
                 └─────────┬───────────┘
                           ↓
       ┌───────────────────┼───────────────────┐
       ↓                   ↓                   ↓
 Project symbols      Context7 docs      GitHub patterns
 Tree-sitter/SCIP                          Zoekt/search
       ↓                   ↓                   ↓
 related tests             └────────┬──────────┘
       └────────────────────────────┘
                           ↓
                     Reranker
                           ↓
                     Context Pack
                       8–15k
                           ↓
                         Codex
                           ↓
              Deterministic verification
                           ↓
             ┌─────────────┴──────────────┐
             ↓                            ↓
           PASS                         FAIL
             ↓                            ↓
           Done              minimal error context
                                          ↓
                                        Codex
```

---

# Итог

Для `Manacost-Labs/Server` не нужно строить ещё одного большого AI-агента.

Нужно сделать инфраструктуру, которая:

1. дешёво понимает задачу;
2. быстро находит нужные символы;
3. автоматически находит связанные тесты;
4. при необходимости получает актуальную документацию;
5. ищет хорошие внешние реализации;
6. отбрасывает слабые результаты;
7. отдаёт Codex небольшой качественный context pack;
8. проверяет результат обычными инструментами;
9. возвращает модели только конкретные ошибки;
10. измеряет реальный эффект через уже существующий benchmark.

Это позволит одновременно улучшить качество кода и сократить расход Codex-токенов без постоянного увеличения расходов на более сильные модели.
