# Единая политика AI-агентов

## Источник

Единственный глобальный источник политики для поддерживаемых AI-клиентов на
этом сервере — [`AGENTS.md`](../AGENTS.md) в репозитории
`/srv/projects/tools/skills`.

## Активные точки входа

Все перечисленные пути должны быть символическими ссылками на источник:

- серверные рабочие корни: `/home/debian/AGENTS.md`, `/srv/projects/AGENTS.md`,
  `/home/debian/server/AGENTS.md`;
- глобальные клиенты: `/home/debian/.codex/AGENTS.md`,
  `/home/debian/.config/opencode/AGENTS.md`, `/home/debian/.claude/CLAUDE.md`,
  `/home/debian/.gemini/GEMINI.md`, `/home/debian/.dsh/AGENTS.md`,
  `/home/debian/.hermes/AGENTS.md`, `/home/debian/.cursor/rules/AGENTS.md`;
- Cursor always-on adapter: `/home/debian/.cursor/rules/manacost-global.mdc`,
  linked to `integrations/cursor/manacost-global.mdc` in this repository.

Проверка:

```bash
/srv/projects/tools/skills/scripts/check-agent-entrypoints.sh
```

Claude Code's model gateway uses the same private OpenRouter credential as the
installed quality CLI. Its key helper, user settings, and verification steps are
in [Claude Code on this server](claude-code-openrouter.md).

Установка глобальных клиентских ссылок:

```bash
/srv/projects/tools/skills/scripts/install-global-agent-entrypoints.sh --adopt-existing
```

Обычные существующие файлы перед заменой перемещаются в тот же каталог с
суффиксом `.legacy-<timestamp>-<pid>`, поэтому миграция обратима. Чужие ссылки,
каталоги и проектные/vendor policy-файлы скрипт не заменяет.

DeepSeek Harness использует официальный user-global путь
`~/.dsh/AGENTS.md`. Hermes подключается через `~/.hermes/AGENTS.md`, но
применяет `AGENTS.md` по цепочке текущего workspace; это не превращает файл в
безусловную инструкцию для каждого произвольного проекта. `SOUL.md` не
заменяется, потому что это отдельный файл личности Hermes.

Глобальное правило Cursor активируется через `alwaysApply: true` в каталоге
`~/.cursor/rules`. Оно направляет агента к тому же абсолютному центральному
`AGENTS.md`; проектные `.cursor/rules/*.mdc` и ближайшие `AGENTS.md` сохраняют
свою более узкую область действия.

## Границы гарантии

Это покрывает Codex, OpenCode, Claude Code, Gemini, DeepSeek Harness, Hermes и
Cursor по обнаруженным на сервере путям. Произвольный AI-клиент может
проигнорировать `AGENTS.md` или Cursor-адаптер, если он не поддерживает
соответствующий механизм файловых инструкций. Ближайший `AGENTS.md` проекта и
vendor-specific policy остаются более узким контекстом и применяются согласно
иерархии в центральной политике.

Hermes обнаруживает `~/.hermes/AGENTS.md` только когда его workspace discovery
достигает этого каталога. Его `SOUL.md` не заменялся. Проверка ссылок подтверждает
единый источник, а не обязательное чтение файла любым клиентом в любой сессии.
