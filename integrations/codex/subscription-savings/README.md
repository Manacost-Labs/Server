# Экономия лимитов ChatGPT/Codex на сервере

Этот каталог фиксирует полный набор механизмов, который используется на сервере
Manacost Labs для уменьшения бесполезного контекста, повторных чтений и запуска
слишком дорогих моделей. Он предназначен для Codex CLI и не меняет тариф или
правила подсчёта лимитов OpenAI.

Главное различие:

- механизмы ниже уменьшают объём данных, который попадает в модель, и количество
  повторной работы;
- это обычно помогает дольше оставаться внутри лимитов подписки;
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

Изображения, аудио, видео и бинарные блоки не перехватываются. При внутренней
ошибке hook работает fail-open: завершает работу с кодом `0`, не ломая исходную
команду Codex. Это важно: `PostToolUse` вызывается после выполнения инструмента,
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

`context-budget` вызывает `tiktoken-cli`, печатает оценку и возвращает код `3`,
если пакет превышает лимит. Серверный порог для передачи сложной задачи или
ревью — 12 000 оценочных tokens:

```bash
context-budget HANDOFF.md
context-budget --limit 8000 docs/ src/selected_file.py
```

Это приблизительная оценка по tokenizer `gpt-4o`, а не официальный счётчик
конкретной модели. Её назначение — остановить явно раздутый handoff до запуска
дорогой сессии.

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

На сервере MCP и внешние инструменты выключены по умолчанию. Это уменьшает
постоянный system/tool schema context и риск случайного широкого поиска. Профиль
включается только когда без него нельзя выполнить текущую задачу.

Профили `code`, `web`, `research`, `github`, `infra`, `typeui` должны уже
существовать в локальном `config.toml`. Скрипт их не создаёт и не меняет.

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
состояние в сессию. Серверный wrapper переопределяет затратные defaults:

| Параметр | Серверное значение |
| --- | --- |
| backend | одноразовый `gpt-5.6-luna`, read-only, medium effort |
| fallback backend | выключен |
| предупреждение | 65% контекста |
| максимум summary | 1 200 tokens |
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
- `tiktoken-cli` для budget gate;
- `repomix` только для `repomix-safe`;
- RTK, compact-plus и codex-usage-monitor — опциональные сторонние компоненты.

Сторонние проекты не устанавливаются автоматически этим репозиторием. Сначала
проверьте upstream, лицензию, release и содержимое install scripts.

### Переносимые скрипты

Скопируйте или добавьте в `PATH` файлы из `bin/`, сохранив executable bit.
`codex-run` ожидает, что `context-budget` также находится в `PATH`.

### Hooks

1. Сделайте резервную копию `~/.codex/config.toml`.
2. Возьмите только нужные блоки из [`config.example.toml`](config.example.toml).
3. Замените placeholders абсолютными локальными путями.
4. Не копируйте `hooks.state` и trusted hashes с другого сервера.
5. Перезапустите Codex, откройте `/hooks`, проверьте команды и доверьте именно
   локальные hashes.
6. Сначала включите ObservationPack, затем compact-plus, затем usage monitor;
   после каждого слоя выполните smoke test.

Не заменяйте весь пользовательский `config.toml`: в нём могут быть unrelated
profiles, MCP, preferences и доверенные hooks.

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
