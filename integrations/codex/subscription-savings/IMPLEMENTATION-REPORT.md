# Итог реализации

Рабочая копия: `/srv/projects/tools/skills-economy-reproducibility-20260921`.
Ветка: `codex/economy-reproducibility-20260921`.
База: `fe257e8db31669356c45182c6a34b55c80379f11` (origin/main на начало работы).
На момент подготовки отчёта, до публикации: Commit: нет. Push: нет.
Deployment: нет. Рабочий серверный config не изменён.

## Результат

1. AGENTS.md: **8870 → 3986 UTF-8 bytes**, уменьшение **55,06% размера файла**.
   Это не процент общей экономии токенов/подписки. Подробные исходные секции
   перенесены в три тематических документа без изменения текста; проверено
   сравнением с HEAD. Иерархия и обязательные ограничения сохранены в root.
2. Добавлен CI-cap: AGENTS.md ≤4500 bytes, Cursor adapter ≤3000 bytes.
3. Полный пример config, семь явных V2-профилей, проверка Codex 0.153.0,
   strict parser и фактического MCP merge. Launcher проверяет также окружение
   текущего проекта перед запуском модели.
4. Явный установщик: dry-run, verify, backup, ownership manifest, повторный
   запуск без изменений, отказ от неизвестных/изменённых конфигов, rollback
   при ошибке записи. Ни одного запуска installer на рабочем home не было.
5. Budget: совместимый tokenizer только для известных моделей; иначе UTF-8
   bytes +15%, явно approximate. Реальные счётчики Codex остаются отдельными.
6. Compaction: короткие/дешёвые интервалы не запускают Luna; пороги настраиваются,
   собственные доступные usage-counters фиксируются, ошибки не блокируют Codex.
7. Benchmark: обязательная сопоставимость задачи/commit/model/effort/speed,
   counters, запусков, API, времени, retries, rework, проверок и качества.
   Реальные результаты не создавались; templates содержат незаполненные поля.
8. Обновлены четыре документа экономии и отдельная инструкция воспроизводимости.

## Проверки

- `make verify`: **PASS**, риск HIGH, **21 проверка**, skipped=[].
- В составе gate — **16 новых offline/profile/E2E tests**, все прошли.
- Настоящий установленный Codex 0.153.0 проверил parser и семь MCP-профилей
  во временном CODEX_HOME, без модели/авторизации; неизвестный параметр отвергнут.
- Проверены exact Unicode archive/recall, поддерживаемый tokenizer/fallback,
  oversized budget, короткая/дешёвая compaction, сброс счётчика, auxiliary usage,
  missing tools/plugin, malformed input, manual senior-model gate, запрет его
  обхода через --model, unknown/user-edited config, backup/idempotence и rollback.
- Исходные context-economy/remote/advisor/ObservationPack/model-routing и
  остальные обязательные проверки также прошли. Один старый тест пакета получил
  больший локальный лимит (500 → 1800) для новой консервативной шкалы; обязательные
  источники и проверки исключения большого необязательного файла сохранены.
- Тестовые журналы: `/tmp/codex-economy-verify.log` (временный локальный файл).
- Отдельные агенты/review не запускались. Проверки live-активации не заявляются.

## Работающие механизмы и границы

Детерминированно проверены меньший root-файл, нулевой MCP allowlist minimal,
предварительные отказы вместо некорректного запуска, точный локальный recall,
консервативный budget gate и пропуск auxiliary compaction по порогам.
Проверена инфраструктура учёта, а не чистая финансовая эффективность.

Не доказаны: экономия подписки, увеличение доступного времени Astra, качество
реальных summaries, реальная парная выборка по трём проектам, работа optional
MCP после авторизации и native hook dispatch после локального доверия команд.
Ранее установленные JEV/Gemma, память и focus не переустанавливались.

## Риски и откат

Версия CLI строго закреплена; обновление требует отдельной проверки pin.
Консервативная шкала отклонит часть старых пакетов. Wrappers требуют соседние
Python-модули; нельзя переносить только bin. Optional MCP требуют отдельной
установки/авторизации. Настройки hooks нужно доверить оператору локально.

В текущем состоянии откат не затрагивает сервер: отказаться от этой изолированной
рабочей копии. После будущей установки восстанавливать только управляемые файлы
по backup/restore.json, предварительно проверив отсутствие пользовательских
изменений; auth, sessions, проекты и plugins не трогать. Подробности и команды:
[REPRODUCIBILITY.md](REPRODUCIBILITY.md).

## Изменённые файлы

- `.ai/verify.json`
- `AGENTS.md`
- `docs/agent-model-policy.md`
- `docs/agent-verification-safety.md`
- `docs/agent-workflow.md`
- `integrations/codex/subscription-savings/CONTEXT-ECONOMY.md`
- `integrations/codex/subscription-savings/ECONOMY-WORKFLOW.md`
- `integrations/codex/subscription-savings/IMPLEMENTATION-REPORT.md`
- `integrations/codex/subscription-savings/README.md`
- `integrations/codex/subscription-savings/REPRODUCIBILITY.md`
- `integrations/codex/subscription-savings/TOKEN-ECONOMY-DECISIONS.md`
- `integrations/codex/subscription-savings/benchmark.py`
- `integrations/codex/subscription-savings/benchmark/baseline.template.json`
- `integrations/codex/subscription-savings/benchmark/economy.template.json`
- `integrations/codex/subscription-savings/bin/codex-context`
- `integrations/codex/subscription-savings/bin/codex-run`
- `integrations/codex/subscription-savings/bin/compact-plus-hook`
- `integrations/codex/subscription-savings/bin/context-budget`
- `integrations/codex/subscription-savings/codex_setup.py`
- `integrations/codex/subscription-savings/compaction_guard.py`
- `integrations/codex/subscription-savings/config.example.toml`
- `integrations/codex/subscription-savings/context_economy/packing.py`
- `integrations/codex/subscription-savings/profiles/code.config.toml`
- `integrations/codex/subscription-savings/profiles/github.config.toml`
- `integrations/codex/subscription-savings/profiles/infra.config.toml`
- `integrations/codex/subscription-savings/profiles/minimal.config.toml`
- `integrations/codex/subscription-savings/profiles/research.config.toml`
- `integrations/codex/subscription-savings/profiles/typeui.config.toml`
- `integrations/codex/subscription-savings/profiles/web.config.toml`
- `integrations/codex/subscription-savings/token_budget.py`
- `scripts/check_context_size.py`
- `tests/test_codex_setup_e2e.py`
- `tests/test_context_economy.py`
