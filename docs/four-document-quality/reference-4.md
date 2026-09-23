# Manacost Context Load Policy
## Правила для Token Economy, Design Guard и Engineering Guard

## Вывод анализа

Три текущих документа вместе занимают примерно 60 KB текста. Их нельзя загружать в каждый запрос Codex.

Они должны быть:
- документацией и source-of-truth;
- разбиты на небольшие модули;
- подключаться только по trigger;
- никогда не добавляться целиком в `AGENTS.md`.

Постоянный контекст должен содержать только правила маршрутизации.

---

# 1. Бюджеты

## Permanent context

Цель:

```text
300–800 tokens
```

Максимум:

```text
~1000 tokens
```

Туда входят только:
- основные ограничения;
- как определить stack/task type;
- какие guards вызвать;
- запрет загружать большие документы целиком.

## Guard instructions

На одну задачу:

```text
1–3 guard modules
~300–700 tokens каждый
```

Обычно:

```text
< 1500 tokens суммарно
```

## Retrieval context

Ориентир:

```text
code/symbols/tests: 5–8k
docs: 1–2k
external examples: 1–3k
architecture/design: 0.5–1k
```

Цель полного дополнительного контекста:

```text
8–15k tokens
```

Не заполнять бюджет только потому, что он доступен.

## Diagnostic packet

После проверки:

```text
обычно < 1000 tokens
hard cap: ~2000 tokens
```

Никаких полных логов.

---

# 2. Главное правило

```text
DO NOT LOAD BY DEFAULT
```

Документы:

```text
manacost-server-token-economy-code-quality.md
manacost-design-quality-system.md
manacost-engineering-guard.md
```

не являются prompt-файлами.

Это reference documentation.

Агент открывает только конкретный раздел/модуль, который нужен текущей задаче.

---

# 3. Permanent Router

В `AGENTS.md` оставить примерно такую логику:

```text
For each task:
1. Detect affected stack and task type from changed/requested paths.
2. Load only applicable guard modules.
3. Prefer deterministic tools over LLM review.
4. Retrieve symbols/tests before broader source reads.
5. Do not load entire guard/reference documents.
6. Keep diagnostic output bounded; return only actionable failures.
7. Escalate retrieval/model/review only when evidence or risk requires it.
```

Этого достаточно как постоянной инструкции.

---

# 4. Trigger-based loading

## Token Economy

Загружать только для:

```text
non-trivial implementation
cross-file debugging
large repository exploration
external library integration
long-running task
```

Не загружать для:

```text
one-line fix
rename
formatting
known-file mechanical edit
```

---

# 5. Design Guard

Загружать только если затрагиваются:

```text
*.tsx
*.jsx
*.css
*.scss
UI components
SVG
images/assets
layout
animation
responsive styles
```

Не загружать для:

```text
backend API
database migration
Go service
CLI
non-UI tests
```

Даже при UI-задаче подключать только нужный модуль.

Пример:

```text
изменение Button
→ tokens + component rules

новый hero
→ tokens + asset preset + responsive

SVG icon
→ SVG rules only
```

Не нужно загружать весь Design Guard.

---

# 6. Engineering Guard

Определять stack по файлам.

## Next.js

Trigger:

```text
.ts
.tsx
.js
.jsx
next.config.*
package.json
```

Подключать только:

```text
nextjs/base
```

Дополнительно:

```text
security → если auth/input/API
performance → если hot path/bundle/rendering
architecture → если меняются boundaries
```

## Go

Trigger:

```text
*.go
go.mod
go.sum
```

Подключать:

```text
go/base
```

Дополнительно только по риску.

## PHP / WordPress

Trigger:

```text
*.php
composer.json
WordPress plugin/theme files
```

Подключать:

```text
wordpress/base
```

Security module автоматически нужен для:

```text
nonce
permissions
REST endpoint
SQL
uploads
authentication
user input
```

---

# 7. Не запускать все проверки всегда

## Fast gate

На обычное изменение:

```text
format
lint
types/static analysis
focused tests
```

## Medium gate

Если меняется поведение:

```text
fast gate
+
security-relevant focused scan
+
integration tests
```

## Heavy gate

Только для:

```text
HIGH/CRITICAL risk
release
dependency update
architecture change
performance-sensitive path
```

Тогда можно запускать:

```text
full Playwright
Trivy
WPScan
race detector
benchmarks
k6
Infection
full visual regression
```

---

# 8. Model calls

## Не использовать LLM если результат можно получить:

```text
AST
compiler
linter
test
static analyzer
git diff
symbol index
visual diff
```

## JEV

Использовать только для:

```text
ambiguous task classification
model/review advisory
retrieval query normalization
```

Если stack/task однозначно определяется путями — JEV не нужен.

## Gemma

Использовать только если:

```text
source/document слишком большой
и
локальное deterministic сокращение недостаточно
```

Если fragment маленький — передать его напрямую.

## Codex

Codex должен получать уже отфильтрованный материал, а не заниматься первичным сканированием проекта.

---

# 9. Retrieval escalation

Всегда начинать с самого дешёвого:

```text
1. known files
2. symbol/AST index
3. lexical/Zoekt
4. related tests
5. project memory
6. Context7
7. external GitHub references
8. embeddings
9. reranker
```

Не запускать все ступени автоматически.

Остановиться, когда получено достаточно доказательств.

---

# 10. Embeddings

Использовать только если:

```text
symbol/lexical search плохо понимает semantic request
```

Не embedding-ить весь repository на каждый запрос.

Индексировать:

```text
changed/new files only
```

Ключ кэша:

```text
repo + commit/file hash + chunk
```

---

# 11. Reranker

Запускать только если кандидатов слишком много.

Пример:

```text
<= 5 candidates
→ reranker не нужен

6–30
→ reranker полезен

>30
→ сначала дешёвый lexical filter
```

Reranker не должен получать сотни полных файлов.

---

# 12. External GitHub reference search

Запускать только когда:

```text
реализуется распространённый внешний pattern
и
локального implementation pattern нет
```

Примеры:

```text
OAuth
rate limiting
webhooks
cache
queues
file upload
```

Не запускать для уникальной бизнес-логики.

Возвращать:

```text
max 2–3 references
только relevant lines
license metadata
```

---

# 13. Context7

Использовать если задача зависит от актуального API библиотеки/framework.

Не использовать:

```text
для внутреннего кода
для простого CSS
для уже известного API, подтверждённого локальным кодом
```

Возвращать только релевантный раздел документации.

---

# 14. Design context

UI-задача получает:

```text
relevant tokens
existing component
relevant story/screenshot
asset preset if needed
responsive rule
```

Не получает:

```text
все tokens
весь Storybook
все screenshots
весь CSS
```

---

# 15. Failure packets

Любой инструмент обязан возвращать компактный результат:

```text
tool/check
file
line
error
severity
related symbol
small relevant diff
related test
```

Не передавать:

```text
полный CI log
полный stdout
весь HTML
полный accessibility tree
весь benchmark output
```

---

# 16. Review context

Reviewer получает:

```text
task
acceptance criteria
relevant architecture/design constraints
git diff
important tests
failed/passed gates
```

Не получает весь repo.

---

# 17. Cache-first

Кэшировать:

```text
file briefs
symbol maps
AST index
external references
Context7 results where version-safe
asset metadata
screenshots
architecture memory
retrieval results
```

Инвалидация по:

```text
file hash
commit
dependency/framework version
design-system revision
```

---

# 18. Concurrency / server load

Для 8-core Ryzen / ~20 GB free RAM:

```text
index workers: 1–2
retrieval workers: 2–4
heavy verification: 1–2 concurrent
embedding/reranker API calls: max 2 concurrent
```

Индексация:

```text
incremental
low priority
changed files only
```

Не запускать full indexing одновременно с benchmarks/load tests.

---

# 19. Suggested modular structure

```text
guards/
├── token/
│   ├── base.md
│   ├── retrieval.md
│   └── external-reference.md
│
├── design/
│   ├── base.md
│   ├── tokens.md
│   ├── components.md
│   ├── assets.md
│   ├── svg.md
│   └── visual-regression.md
│
└── engineering/
    ├── shared-security.md
    ├── nextjs-base.md
    ├── nextjs-performance.md
    ├── go-base.md
    ├── go-performance.md
    ├── wordpress-base.md
    └── wordpress-security.md
```

Каждый модуль:

```text
~200–700 tokens
```

---

# 20. Hard rules

1. Never load all three large documents into model context.
2. Never load an entire guard family when one module is enough.
3. Never use an LLM for deterministic checks.
4. Never send full logs when a bounded diagnostic is possible.
5. Never run embeddings/reranking before lexical/symbol search.
6. Never run external reference search if local evidence is sufficient.
7. Never repeat retrieval when version-safe cache is valid.
8. Never send the whole repository to a reviewer.
9. Never run heavy gates for LOW-risk mechanical changes.
10. Stop retrieval/check escalation as soon as acceptance evidence is sufficient.

---

# 21. Recommended default

Для обычной задачи:

```text
Permanent router         ~500 tokens
Stack guard              ~400–700
Task-specific guard      ~300–600
Architecture memory      ~500
Retrieved source/tests   ~4–8k
Optional docs/reference  ~1–3k
```

То есть вместо загрузки десятков тысяч токенов правил агент обычно получает небольшой целевой пакет.

---

# Итог

Три больших документа следует оставить как полную документацию для человека и редких глубоких задач.

Для Codex нужна другая форма:

```text
tiny router
→ detect task
→ load 1–3 tiny modules
→ deterministic retrieval/checks
→ bounded context
→ Codex
→ compact failures only
```

Именно эта схема сохраняет преимущества Token Economy, Design Guard и Engineering Guard, не превращая их самих в источник расхода токенов.
