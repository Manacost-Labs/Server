# Экономия лимитов ChatGPT/Codex на сервере

Дополнение: [подготовка контекста, проверяемая память, измерения и TypeSafe](CONTEXT-ECONOMY.md).
Новый CLI работает явно и не меняет установленную конфигурацию сервера.

Этот каталог содержит исходники механизмов экономии. Состояние исходников,
установка на сервере и доказанная эффективность различаются; см.
[воспроизводимую настройку и матрицу доказательств](REPRODUCIBILITY.md). Он предназначен для Codex CLI и не меняет тариф или
правила подсчёта лимитов OpenAI.

Главное различие:

- механизмы ниже уменьшают объём данных, который попадает в модель, и количество
  повторной работы;
- влияние на длительность работы в пределах подписки требует измерений;
- процент экономии вывода инструментов нельзя выдавать за такой же процент
  экономии общего лимита подписки: в лимит также входят системный prompt,
  история, рассуждение, ответы модели и прочие служебные данные.

Снимок серверной установки сделан 18 сентября 2026 года: Codex CLI `0.153.0`,
RTK `0.49.0`, compact-plus `v1.3.2`, codex-usage-monitor `0.1.0`.

## Карта механизмов

| Уровень | Механизм | Что экономит | Где находится |
| --- | --- | --- | --- |
| До запуска команды | RTK | Убирает шум из `git`, тестов, логов, JSON, файлов и других CLI-ответов | Внешний бинарник [`rtk`](https://github.com/rtk-ai/rtk) |
| После команды | ObservationPack | Заменяет большой текстовый tool result коротким preview и локальной квитанцией | [`observation_pack.py`](observation_pack.py) |
| До передачи контекста | `context-budget` | Не даёт отправить модели пакет больше установленного бюджета | [`bin/context-budget`](bin/context-budget) |
| При сборке handoff | `repomix-safe` | Собирает только явно выбранные файлы, исключает типовые секреты и проверяет итоговый бюджет | [`bin/repomix-safe`](bin/repomix-safe) |
| При старте Codex | `codex-context` | Не загружает web/GitHub/infra MCP и инструменты, если они не нужны задаче | [`bin/codex-context`](bin/codex-context) |
| При выборе модели | `codex-run` и dispatch | Отдаёт короткие задачи дешёвой роли и требует ограниченный пакет для старших моделей | [`bin/codex-run`](bin/codex-run), [model routing](../../../docs/model-routing.md) |
| На длинной сессии | compact-plus wrapper | Создаёт ограниченный checkpoint перед compaction и восстанавливает состояние без повторного исследования | [`bin/compact-plus-hook`](bin/compact-plus-hook) |
| На уровне правил | Контекстная дисциплина | Ограничивает чтение файлов, логи, web-страницы, число skills и повторные проверки | [`AGENTS.md`](../../../AGENTS.md) |
| Измерение | codex-usage-monitor | Показывает usage, context, cache hits и API-equivalent cost; сам по себе токены не режет | [внешний plugin](https://github.com/harveyxiacn/codex-usage-monitor) |

Эти слои дополняют друг друга. RTK уменьшает вывод до попадания в hook.
ObservationPack страхует команды, которые всё же вернули слишком много текста.
Compaction и checkpoints уменьшают повторную работу на длинной сессии. Model
routing не тратит старшую модель на задачу, которую уверенно решает младшая.

## 1. RTK: компактный вывод команд

На сервере политика рекомендует `rtk` для исследовательских команд, статуса Git
и тестов. Это прокси над обычными CLI-командами: он оставляет ошибки и значимые
строки, но удаляет повторяющиеся рамки, успешный шум и громоздкое форматирование.

Примеры:

```bash
rtk git status
rtk test pytest -q
rtk json large-result.json
rtk read src/large_file.py
rtk aws s3 ls s3://example-bucket/
```

Когда нужен точный diff, машинный JSON или полный текст ошибки, используется
обычная команда с собственным ограничением строк. RTK нельзя применять там,
где фильтрация изменит данные, предназначенные не модели, а следующей программе.

RTK — сторонний проект и в этот репозиторий не копируется. Проверяйте его
актуальную лицензию, release и checksum в upstream перед установкой.

## 2. ObservationPack: страховка от большого tool output

`observation_pack.py` — локальный `PostToolUse` hook на стандартной библиотеке
Python. Для текстового результата размером от 6 KiB он:

1. сериализует результат без удалённого вызова модели;
2. сохраняет точный текст в gzip-архив с SHA-256;
3. возвращает модели первые 1 200 и последние 800 символов;
4. добавляет стабильный ID и точную команду постраничного recall;
5. удаляет записи старше семи дней и удерживает архив в пределах 512 MiB;
6. ведёт ограниченный 8 MiB JSONL-журнал метрик.

Лимит учитывает завершённые записи, orphan-файлы и остатки прерванной атомарной
записи. Если новая запись сама не помещается в настроенный cap, она удаляется,
а исходный tool result пропускается без замены, чтобы recall не указывал на
несуществующий архив.

Изображения, аудио, видео и бинарные блоки не перехватываются. При внутренней
ошибке hook, чтения stdin или конфигурации окружения hook работает fail-open:
завершает работу с кодом `0`, не ломая исходную команду Codex. Это важно:
`PostToolUse` вызывается после выполнения инструмента,
а `decision = "block"` в совместимом с Codex `0.153.0` ответе заменяет только
видимый модели результат, а не откатывает side effect команды.

### Настройки окружения

| Переменная | Значение по умолчанию |
| --- | --- |
| `CODEX_OBSERVATION_PACK_DIR` | `~/.local/state/codex-observation-pack` |
| `CODEX_OBSERVATION_PACK_MIN_BYTES` | `6144` |
| `CODEX_OBSERVATION_PACK_HEAD_CHARS` | `1200` |
| `CODEX_OBSERVATION_PACK_TAIL_CHARS` | `800` |
| `CODEX_OBSERVATION_PACK_TTL_SECONDS` | `604800` |
| `CODEX_OBSERVATION_PACK_MAX_BYTES` | `536870912` |
| `CODEX_OBSERVATION_PACK_MAX_METRICS_BYTES` | `8388608` |
| `CODEX_OBSERVATION_PACK_MAX_INPUT_BYTES` | `67108864` |

### Команды

```bash
python3 observation_pack.py stats
python3 observation_pack.py recall OBSERVATION_ID --start-line 1 --lines 200
python3 observation_pack.py cleanup
```

`recall` ограничен 1 000 строками за вызов. ID допускает только 24 hex-символа;
archive directory и файлы получают права `0700` и `0600`; symlink для каталога,
metadata или gzip-записи отклоняется.

### Фактическое измерение

Проверочный вызов на этом сервере сократил видимый текстовый tool result с
8 110 до 2 409 байт — на 5 701 байт, или 70,3%. Снимок накопленных локальных
метрик 18 сентября 2026 года:

```text
results: 705
archived_results: 112
original_bytes: 5 790 141
visible_bytes: 1 339 905
estimated_saved_bytes: 4 450 236
estimated_savings_percent: 76.86
local_state_size: 3.7 MiB
```

Это измерение только model-visible tool responses, а не общего расхода
подписки. Накопленная выборка включает тестовые и рабочие вызовы и не является
универсальным benchmark.

Концептуальное направление — хранить полное наблюдение вне активного контекста
и возвращать его по требованию — близко к [NVIDIA SoL-Pi](https://github.com/NVlabs/SoL-Pi).
Код здесь написан независимо, не запускает внешний reducer и не отправляет
архивы в сеть.

## 3. Budget gate и безопасный handoff

`context-budget` печатает JSON с методом, моделью и запасом; возвращает код `3`,
если пакет превышает лимит. Серверный порог для передачи сложной задачи или
ревью — 12 000 оценочных tokens:

```bash
context-budget HANDOFF.md
context-budget --limit 8000 docs/ src/selected_file.py
```

Для точно известных моделей применяется совместимый tokenizer, если установлен
`tiktoken`. Для GPT-5.6/GPT-6 без подтверждённого tokenizer используется
консервативная оценка UTF-8 bytes + 15%. Это не реальные счётчики Codex; скрытый
prompt и история не включены. Старые численные пороги могут стать строже.

`repomix-safe` добавляет к этому четыре ограничения:

- обязательный allowlist через `--include`;
- обязательный конечный файл через `--output`;
- исключение `.env`, ключей, сертификатов, БД и dump-файлов;
- повторная проверка полученного пакета через `context-budget`.

```bash
repomix-safe /srv/project \
  --include 'src/**,tests/test_feature.py' \
  --output /tmp/feature-handoff.md \
  --compress \
  --budget 12000
```

Ignore-список — защита от частых ошибок, но не полноценный secret scanner.
Перед внешней передачей пакет всё равно нужно просмотреть.

## 4. Минимальный профиль инструментов

`codex-context` запускает Codex с минимальным набором возможностей или с одним
явно выбранным профилем:

```bash
codex-context minimal
codex-context code
codex-context web
codex-context github
```

В поставляемом примере все MCP выключены в базе. Каждый V2-профиль явно
включает свой набор в `<name>.config.toml`. `minimal` также проходит через `-p`
и проверку фактического allowlist. Недостающий профиль, несовместимая версия
Codex или отсутствующая команда дают понятную ошибку до запуска модели.
Рабочий серверный конфиг этой поставкой не изменён; в нём могут быть другие defaults.

## 5. Маршрутизация моделей

`codex-run` даёт короткие имена четырём ролям:

| Имя | Модель | Назначение на сервере |
| --- | --- | --- |
| `luna` | `gpt-5.6-luna` | короткий факт, узкий поиск, triage, механическая правка |
| `terra` | `gpt-5.6-terra` | обычная реализация и тесты |
| `sol` | `gpt-5.6-sol` | только явно обоснованная сложная задача или ревью |
| `astra` | `gpt-6-astra` | только явно обоснованное трудное решение/ревью |

Для `sol` и `astra` wrapper требует одновременно конкретную причину и один
существующий handoff-файл, который проходит `context-budget`:

```bash
codex-run terra code
codex-run sol --reason 'review distributed lock correctness' \
  --package /tmp/lock-review.md code
```

Это техническая защита от случайного дорогого запуска, а не разрешение на него:
политика сервера дополнительно требует явного запроса пользователя.

В самом репозитории уже есть более строгий opt-in dispatch:
[`scripts/manacost-dispatch`](../../../scripts/manacost-dispatch) и
[`scripts/skillctl`](../../../scripts/skillctl). Он строит JSON-план, проверяет
доступность модели/effort, ограничивает retries и не запускается без
`--execute`. Подробный контракт находится в
[`docs/model-routing.md`](../../../docs/model-routing.md).

## 6. Управляемая compaction без повторного исследования

[compact-plus](https://github.com/u-ichi/compact-plus) сохраняет transcript и
ограниченный state summary перед compaction, после чего возвращает проверяемое
состояние в сессию. Новый wrapper добавляет измеряемый порог перед дополнительным вызовом модели:

| Параметр | Серверное значение |
| --- | --- |
| backend | одноразовый `gpt-5.6-luna`, read-only, low effort, только после порога |
| fallback backend | выключен |
| предупреждение | 65% контекста |
| summary | инструкция plugin: 1 200 tokens; проверка ответа: 12 000 UTF-8 bytes, не жёсткий лимит генерации |
| timeout | 45 секунд |
| squash | включён |
| прочитанные строки | 80 |
| bash preview | 800 символов |
| two-pass summary | выключен |

Wrapper живёт отдельно от plugin checkout, поэтому обновление plugin не
возвращает его исходные дорогие defaults. Он ожидает установленный compact-plus
в `${CODEX_HOME:-$HOME/.codex}/plugins/compact-plus`; путь можно заменить через
`COMPACT_PLUS_PLUGIN_ROOT`.

Compaction полезна после завершённой фазы, решения, проверки, ошибки, паузы или
handoff. Слишком частая compaction сама тратит токены и ухудшает точность, поэтому
она не запускается на каждом сообщении.

## 7. Политика контекстной дисциплины

[`AGENTS.md`](../../../AGENTS.md) и серверный bootstrap обеспечивают экономию,
которую нельзя надёжно выразить одним hook:

- сначала один конкретный вопрос и один точечный поиск;
- вывод каждого инструмента обычно не больше 2 000 tokens;
- никаких recursive listings, полных web-страниц, таблиц БД и длинных логов;
- только релевантные диапазоны файлов и один существующий пример;
- обычно 0–1 skill для простой, 1–3 для обычной и до 4–5 для сложной задачи;
- краткий scout/brief вместо передачи всего репозитория;
- продолжение рабочей сессии вместо автоматического рестарта;
- новый task после существенной смены цели;
- checkpoints только в устойчивых точках, а не после каждого шага;
- повтор тестов только при появлении нового evidence.

Такие правила уменьшают не только input context, но и повторные tool calls,
перечитывание файлов и циклы «исследовать всё заново».

## 8. Измерение через codex-usage-monitor

[codex-usage-monitor](https://github.com/harveyxiacn/codex-usage-monitor)
подключён к событию `Stop` и показывает model, reasoning effort, context,
cache hits, usage и API-equivalent cost. Он нужен для проверки результата и
поиска регрессий, но не является самостоятельным механизмом сокращения.

```bash
codex-usage-monitor summary
codex-usage-monitor statusline
codex-usage-monitor doctor
```

Не интерпретируйте API-equivalent cost как счёт к подписке ChatGPT: это
сравнительная оценка, полезная для тренда между сессиями.

## Установка

### Зависимости

- Linux, Bash, Python 3.11+;
- Codex CLI с hooks;
- Python 3.11+; `tiktoken` необязателен для известных моделей;
- `repomix` только для `repomix-safe`;
- RTK, compact-plus и codex-usage-monitor — опциональные сторонние компоненты.

Сторонние проекты не устанавливаются автоматически этим репозиторием. Сначала
проверьте upstream, лицензию, release и содержимое install scripts.

### Переносимые скрипты и hooks

Сохраняйте `bin/` вместе с соседними Python-модулями и профилями: wrappers
разрешают реальный путь symlink. Копирование только bin больше не поддерживается.
Используйте [установщик](REPRODUCIBILITY.md): сначала `--dry-run`, затем явный
`--install` в выбранный `CODEX_HOME`, затем `--verify`. Чужой конфиг не перезаписывается.
Не копируйте trust hashes; команды hooks проверяются оператором через `/hooks`.

## Проверка

Из корня репозитория:

```bash
python3 -B -m unittest -v tests/test_observation_pack.py
python3 -m py_compile integrations/codex/subscription-savings/observation_pack.py
shellcheck integrations/codex/subscription-savings/bin/*
VERIFY_RISK=HIGH make verify
```

Smoke test hook без изменения реального state:

```bash
tmp_state=$(mktemp -d)
CODEX_OBSERVATION_PACK_DIR="$tmp_state" \
CODEX_OBSERVATION_PACK_MIN_BYTES=10 \
python3 integrations/codex/subscription-savings/observation_pack.py <<'JSON'
{"hook_event_name":"PostToolUse","tool_name":"test","tool_use_id":"1","tool_response":"this is deliberately longer than ten bytes"}
JSON
```

После проверки удалите только созданный временный каталог.

## Безопасность и данные

- ObservationPack хранит полный вывод инструментов локально. Если команда
  напечатала секрет, он окажется в archive до TTL/cleanup. Не печатайте секреты.
- Архив не синхронизируется в Git, S3 или внешний reducer.
- Файлы состояния нельзя добавлять в репозиторий.
- Preview остаётся недоверенным tool output; теги в receipt напоминают модели,
  что текст не является инструкцией.
- `repomix-safe` отсекает типовые секретные файлы, но не гарантирует отсутствие
  ключа внутри обычного `.py` или `.md`.
- compact-plus обрабатывает transcript; изучите его политику данных перед
  использованием другого backend.
- Hooks выполняют локальные команды с правами пользователя Codex. Доверяйте
  только просмотренному пути и конкретному hash.

## Откат

1. Через `/hooks` отключите подозрительный hook или удалите только его блок из
   `config.toml`.
2. Перезапустите Codex и проверьте обычную команду.
3. Для ObservationPack сохранённые records можно оставить до TTL или удалить
   отдельно после проверки точного state path.
4. Удаление wrapper из `PATH` не меняет существующий `config.toml`; сначала
   уберите ссылки на него.
5. Не восстанавливайте целиком старый config поверх новых unrelated настроек.

## Ограничения

- ObservationPack использует legacy feedback shape, проверенный на Codex
  `0.153.0`. После обновления Codex нужно повторить live smoke test по
  [официальному hooks contract](https://developers.openai.com/docs/hooks).
- Preview head/tail может пропустить важную строку в середине. Для этого receipt
  содержит точный pageable recall.
- Очень сжимаемый текст почти не занимает диск, но всё равно мог быть дорогим
  до hook; поэтому RTK остаётся первым уровнем.
- Ни один из механизмов не гарантирует конкретный процент экономии подписки.
- Автоматический remote reducer, S3 для tool output, Action Fusion и
  принудительная compaction не включены: они требуют отдельной модели угроз,
  измерений и явного разрешения.

## Источники и лицензии

- [Codex hooks](https://developers.openai.com/docs/hooks) — официальный контракт.
- [RTK](https://github.com/rtk-ai/rtk) — сторонний CLI; лицензия в upstream.
- [compact-plus](https://github.com/u-ichi/compact-plus) — MIT, внешний plugin.
- [codex-usage-monitor](https://github.com/harveyxiacn/codex-usage-monitor) — MIT, внешний plugin.
- [NVIDIA SoL-Pi](https://github.com/NVlabs/SoL-Pi) — исследовательское вдохновение; его код сюда не копировался.
# Explicit Gemma prompt preparation

Use this for a selected substantial task before launching Codex. It does not
intercept desktop messages, change the selected model, rewrite project policy,
or enable a prompt hook. Only the named UTF-8 prompt file is sent to OpenRouter;
history, repository files and memory are not included. Review the selected file
for private material first; credential pattern screening is not complete DLP.

```sh
# task.txt is relative to the selected project; preview makes no API/model call.
context-economy --project /path/to/project prompt-brief \
  --prompt-file task.txt --preview-remote

# Prepare private original, combined prompt and measurement report artifacts.
context-economy --project /path/to/project prompt-brief \
  --prompt-file task.txt --allow-remote

# Or prepare, then explicitly launch Astra through the existing manual gate.
context-economy --project /path/to/project prompt-brief \
  --prompt-file task.txt --allow-remote --launch astra \
  --reason 'Resolve the documented concurrency design decision' --profile code
```

The JSON result names `original`, `prepared` and `report` files (mode 600 in
private project state). For Codex Desktop, paste the contents of `prepared` into
the selected task yourself. Running the CLI launcher opens a CLI session; it
does not replace a message in an existing desktop task. Without `--launch`, no
Codex model is called. Without `--allow-remote`, the original alone is saved.

Gemma `google/gemma-4-26b-a4b-it` organizes exact source quotations into goal,
acceptance criteria, constraints, unverified source context and existing open questions. Validation
rejects invented text, unexpected fields, duplicates, incomplete responses and
oversized extracts. Classification can still be wrong and omissions are possible:
the full original is retained as authoritative user content, and the extract is
explicitly untrusted reference data. Nothing is injected as developer context.

Prompts under 600 characters skip Gemma. Prompts over 8000 UTF-8 bytes are rejected
without truncation. Extract JSON is at most 3000 bytes and half the original byte
size, with a 1024-token provider output limit. Final packets are checked against
the conservative 12000-token estimate; an oversized combined packet falls back
to the original. Launch rechecks that budget and preserves the existing senior
reason/package gate and selected capability profile. Short follow-ups should go
straight to the existing task; length alone cannot recognize every continuation.

The helper reuses the shared OpenRouter ledger (maximum $1 per rolling 24 hours),
price ceilings, one-hour cache and a maximum 15-second request timeout. There are
no application retries or provider fallbacks. Missing credentials, exhausted
budget, remote failure or invalid output retain the original; a failed request
may still cost money and keeps its ledger reservation when cost is unknown.
The configured timeout bounds socket operations, not a hard end-to-end deadline.

Adding a brief usually **increases** Astra input. The report records byte counts,
estimated input and provider-reported cost when available, never subscription
savings. Compare quality, rework, latency and measured usage on matched real tasks
before enabling broader use. Normal tests mock OpenRouter and never spend money.
