# Каталог рассмотренных инструментов экономии контекста

Сохранено 2026-09-21. Это список исследований и решений, не список установок.
Исторические оценки первого исследования сохранены; перед внедрением заново
проверять совместимость, лицензию, цену и актуальную версию. Проценты авторских
бенчмарков не являются измеренной экономией нашей подписки.
Принципы и следующий пилот: [TOKEN-ECONOMY-DECISIONS.md](TOKEN-ECONOMY-DECISIONS.md).

## Имеющаяся основа

ai-memory v2.3.2 развёрнут отдельно для Hearthpulse, Hearthstone API и WordPress.
Запись явных проверенных заметок, локальный поиск, TTL/source hashes; LLM и
embeddings сервиса отключены. CLI context-economy объединяет память, pack,
архивирование вывода и отчёты. RTK, ObservationPack, context-budget и
codex-context уже присутствовали в рабочем процессе. Gemma не подключена;
TypeSafe-адаптер реализован, но выключен. Автоматические старые hooks имеют
собственное поведение и не считаются бесплатными по факту установки ai-memory.

## Первое исследование

| Инструмент | Назначение | Сохранённое решение |
| --- | --- | --- |
| [RTK](https://github.com/rtk-ai/rtk) | Компактный вывод CLI | Измерять покрытие уже используемых команд |
| [Serena](https://github.com/oraios/serena) | Символы, ссылки, LSP | Использовать адресно; учитывать пересечение с CodeGraph |
| [ast-grep](https://github.com/ast-grep/ast-grep) | Поиск структурных шаблонов | Лёгкий кандидат без обязательного модельного API |
| [Context Mode](https://github.com/mksglu/context-mode) | Обработка и поиск больших результатов вне контекста | Отдельный пилот; пересечение с ObservationPack |
| [QMD](https://github.com/tobi/qmd) | Поиск локальной документации | При наличии значимого корпуса документов |
| [jCodeMunch](https://github.com/jgravelle/jcodemunch-mcp) | Извлечение кода по символам | Сравнить с имеющимися средствами; проверить коммерческие условия |
| [jDocMunch](https://github.com/jgravelle/jdocmunch-mcp) | Извлечение документации | После оценки QMD; проверить коммерческие условия |
| [compact-plus](https://github.com/u-ichi/compact-plus) | Восстановление после компактации | Измерять пользу и собственные модельные вызовы |
| [codex-usage-monitor](https://github.com/harveyxiacn/codex-usage-monitor) | Счётчики использования | Измеритель, не самостоятельная экономия |
| [ccusage](https://github.com/ccusage/ccusage) | Отчёты CLI | Альтернативный отчёт; избегать дублирования |
| [CodexBar](https://github.com/steipete/CodexBar) | Видимость лимитов | Удобство контроля, не уменьшение расхода само по себе |
| [Memvid](https://github.com/memvid/memvid) | Переносимое хранилище памяти | Пока пересекается с текущей памятью |
| [Claude Context](https://github.com/zilliztech/claude-context) | Семантический поиск кода | Низкий приоритет из-за дополнительной инфраструктуры |
| [ai-memory](https://github.com/akitaonrails/ai-memory) | Межсессионная память | Уже развёрнут локально; см. AI-MEMORY.md |

## Дополнительное исследование Product Design Research

| Инструмент | Механизм | Решение |
| --- | --- | --- |
| [Probe](https://github.com/probelabs/probe) | AST-aware поиск, token budget, устранение повторов; Python/TS/PHP | Первый поисковый пилот на API; без embedding-сервиса |
| [Playwright CLI](https://github.com/microsoft/playwright-cli) | Снимки в файлы, отдельные элементы, ограничение глубины | Пилот на Hearthpulse; проверить реальное преимущество |
| [agent-browser](https://github.com/vercel-labs/agent-browser) | Компактные снимки, diff, скриншоты при изменении | Альтернатива Playwright CLI; выбрать один |
| [Codanna](https://github.com/bartolli/codanna) | Индекс символов, граф вызовов, локальный semantic search | Позже; сравнить с CodeGraph/Serena перед дополнительным индексом |
| [Headroom](https://github.com/headroomlabs-ai/headroom) | Сжатие вывода, SDK/proxy/agent wrapper | Только отдельный эксперимент: wrapper меняет маршрут и добавляет Serena по умолчанию |
| [LLMLingua-2](https://github.com/microsoft/LLMLingua) | Модельное сжатие текста | Низкий приоритет; проверять потерю деталей и стоимость подготовки |
| [GitNexus](https://github.com/abhigyanpatwari/GitNexus) | Граф кода и анализ влияния | Отложить; PolyForm Noncommercial требует отдельной проверки условий |

Поиск кода проверять на API; браузерные сценарии — на Hearthpulse и
hs-manacost.ru. Статус установки перечисленных кандидатов не менялся в ходе
исследования. Конфигурацию браузера клиента не подменять автоматически.

## Дешёвые модели как дополнительный этап

- [TypeSafe JEV](https://docs.typesafe.ai/introduction): классификация и
  ранжирование; сначала shadow-пилот. Реализованный active только меняет порядок.
- [Google Gemma 4 26B A4B IT](https://huggingface.co/google/gemma-4-26B-A4B-it):
  извлечение и краткие справочные пакеты; адаптер пока является предложением.

Тарифы, ограничения, роли и критерии допуска записаны в документе решений.
Ни одна из этих моделей не пополняет подписку ChatGPT: потенциальный эффект
получается за счёт замещения части работы Astra отдельными API-вызовами.

## Карта свидетельств

Исследовались README/метаданные семи новых репозиториев, отдельные issues Codex
и сообщения Hacker News. [Большие результаты и компактация](https://github.com/openai/codex/issues/32888),
[длинные сессии](https://github.com/openai/codex/issues/44884),
[рост контекста](https://github.com/openai/codex/issues/44305),
[пакетирование](https://github.com/openai/codex/issues/41450),
[непродуктивные повторы](https://github.com/openai/codex/issues/43452).
[Комментарий о CLI/MCP](https://news.ycombinator.com/item?id=49788468) — отдельный
опыт пользователя, не статистика. Доказательств распространённости и независимых
замеров экономии на наших задачах недостаточно. Маркетинговые проценты не приняты
как целевые показатели. Новые инструменты в исследовании не запускались.
