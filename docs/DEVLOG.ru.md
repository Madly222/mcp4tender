# Tender Engine

Конфигурируемый движок для ежедневного мониторинга и анализа тендеров.
Ядро (engine) ничего не знает про тендеры — оно прогоняет ступени (stages)
по конфигу. Тендер-монитор — первая конфигурация поверх движка.

## Принцип

- Кор (неизменный): контракт ступени, реестр, БД, config-store с
  версионированием и горячей перезагрузкой, оркестратор, планировщик, проверки.
- Опции (данные, меняются без правки кода): пайплайны, расписание, пороги,
  источники, промпты, выбор модели — всё в БД как версионируемый конфиг.

## Команды (CLI)

```
python3 app.py check               # проверки при старте (БД, схема, конфиги, ступени)
python3 app.py run pipeline.demo   # один прогон пайплайна сейчас
python3 app.py serve               # демон-планировщик (по расписанию из конфига)
python3 app.py demo                # демонстрационный прогон

python3 tools/inspect.py runs      # последние прогоны пайплайнов
python3 tools/inspect.py stages    # последние ступени (статус, токены, ошибки)
python3 tools/inspect.py tenders   # тендеры в БД
python3 tools/inspect.py verdicts  # вердикты
python3 tools/inspect.py configs   # активные конфиги (с версиями)
python3 tools/inspect.py audit     # журнал изменений
# у всех команд кроме configs есть -n N (сколько строк)
```

## Запуск из домашней папки (без sudo, без venv)

Фаза 0-1 — чистый stdlib, зависимостей ноль.

```
cd ~/tenderengine
python3 app.py check
python3 tests/test_phase0.py
python3 tests/test_phase1.py
```

## Демон (выбери один способ)

A) user-level systemd (без sudo, переживает разлогин при включённом linger):
```
mkdir -p ~/.config/systemd/user
cp ~/tenderengine/deploy/tenderengine.user.service ~/.config/systemd/user/tenderengine.service
systemctl --user daemon-reload
systemctl --user enable --now tenderengine
systemctl --user status tenderengine
journalctl --user -u tenderengine -f
# чтобы работал без активной сессии (если разрешено):
loginctl enable-linger $USER
```

B) nohup (самый простой fallback):
```
cd ~/tenderengine
nohup python3 app.py serve > serve.log 2>&1 &
tail -f serve.log
# остановить: pkill -f "app.py serve"
```

C) system-level systemd (если есть sudo и /opt) — см. deploy/tenderengine.service.

## Расписание

Меняется через конфиг `schedule.jobs` (по умолчанию выключено). Пример:
```
[{"pipeline": "pipeline.demo", "at": ["03:00"], "enabled": true},
 {"pipeline": "pipeline.demo", "every_minutes": 30, "enabled": false}]
```
"at" — список времён HH:MM; "every_minutes" — интервал. Режим nightly/двухфазный =
какие задания включены. Планировщик подхватывает изменения конфига на лету.

## Бэкап

Скопировать `data/tenderengine.db` (+ `-wal`/`-shm`) через WinSCP.

## Слой данных

SQLite (один файл). Доступ изолирован в engine/db.py — переход на Postgres при
мультитенантности не затрагивает ступени.

## Фаза 2: коллекторы (MTender)

Источники — в конфиге `sources.<имя>`, не в коде. Первый: MTender (OCDS JSON).

```
# посмотреть реальную форму ответа источника (курсор, поля) на боевом сервере:
python3 app.py probe mtender

# включить источник и задать параметры:
python3 tools/config_cli.py set sources.mtender '{"enabled": true, "list_url": "https://public.mtender.gov.md/tenders", "record_url_template": "https://public.mtender.gov.md/tenders/{ocid}", "timeout": 30, "page_limit": 1, "max_records_per_run": 20, "backfill_days": 7}'

# собрать тендеры:
python3 app.py collect mtender

# посмотреть результат:
python3 tools/view.py sources    # история прогонов источника (fetched/new/cursor)
python3 tools/view.py tenders    # собранные тендеры
```

Коллектор инкрементальный: курсор хранится в `source_state`, при пустом курсоре
стартует с `now - backfill_days`. Объём по каждому прогону пишется в `source_runs`
(задел под мониторинг охвата / антипропуск на Фазе 7).

## Редактор конфигов (CLI, до веб-морды)

```
python3 tools/config_cli.py list
python3 tools/config_cli.py get <key>
python3 tools/config_cli.py set <key> '<json>'
python3 tools/config_cli.py history <key>
python3 tools/config_cli.py rollback <key> <version>
```

## Смотрелка (read-only)

`python3 tools/view.py [runs|stages|tenders|verdicts|configs|audit|sources] [-n N]`

## Фаза 3: триаж (без LLM)

Скоринг по весам из конфига, раскладка в 3 корзины, ничего не удаляется (только метка + причина).

```
python3 app.py triage            # прогнать триаж по тендерам со статусом new/updated
python3 tools/view.py triage     # тендеры с корзиной/скором, по убыванию релевантности
```

Веса меняются на лету через config_cli (релевантность = ваши ниши):
```
python3 tools/config_cli.py get triage.cpv_weights
python3 tools/config_cli.py set triage.keyword_weights '{"dron":3,"camera":2,...}'
python3 tools/config_cli.py set triage.bucket_thresholds '{"relevant":3,"gray":0.5}'
```
Корзины: relevant (>= relevant) -> сразу в дальнейший анализ; gray (>= gray) -> страховочная
сетка (на Фазе 5 досматривает дешёвая модель); out (< gray) -> не анализируем, но храним
с причиной. Пороги — веса, а не жёсткие ворота: любой положительный сигнал даёт минимум gray.

## renormalize (без сети)

После изменения нормализатора переприменить его к уже скачанным записям без повторных HTTP:
```
python3 app.py renormalize mtender
```

## Фаза 4A: venv + LLM-шлюз

Первая фаза с зависимостями. Поднять venv (без sudo) и поставить пакеты:
```
cd ~/tenderengine
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```
С этого момента запускать через `.venv/bin/python` (чтобы был доступен Anthropic SDK):
```
.venv/bin/python app.py check
```

Ключ Anthropic — в окружении (НЕ в коде/конфиге). Создать `~/tenderengine/.env`:
```
echo 'ANTHROPIC_API_KEY=sk-ant-...' > ~/tenderengine/.env
```
Для разовых команд: `export ANTHROPIC_API_KEY=sk-ant-...` перед запуском.
user-systemd-юнит уже читает `.env` и запускает через `.venv/bin/python`.

Проверка шлюза:
```
.venv/bin/python app.py llm-test --text "Spune OK"
```
Без ключа провайдер автоматически = stub (бесплатно, для отладки механики).
С ключом = anthropic, реальный вызов + учёт токенов/стоимости.

Настройки шлюза (config_cli):
```
llm.provider     auto | anthropic | stub
llm.models       {"default":"...","extract":"...","applicability":"..."}  модель на ступень
llm.pricing      {model:{"in":$/Mtok,"out":$/Mtok}}  ПЛЕЙСХОЛДЕРЫ — обнови под актуальные цены
llm.cache_enabled true  (кэш ответов по хэшу: повтор не тарифицируется)
```

## Фаза 4B: чтение документов

PDF — через PyMuPDF (без системных зависимостей), DOCX — python-docx. Сканы
(мало текста на страницу) рендерятся в картинки и читаются зрением модели (OCR без tesseract).
Файлы кэшируются в `data/docs/` (повторно не качаются).

```
.venv/bin/python app.py read-doc <tender_id>
```
Берёт документы тендера типов biddingDocuments/tenderNotice, качает, извлекает текст;
для скана — vision OCR (стоит немного токенов). Печатает method (text|vision|skipped),
число символов, стоимость и начало текста. Настройки — ключи documents.* в конфиге.

## Фаза 4C: извлечение полей ТЗ

Берёт caiet de sarcini релевантных/серых тендеров, локально вырезает техсекцию
(отбрасывая типовой шаблон Минфина — экономия токенов), отдаёт Haiku и достаёт
структуру: объект, технические требования, СПИСОК ТЕХНИКИ (вход для Фазы 6),
сроки, квалификация, оценочная стоимость.

```
.venv/bin/python app.py extract --limit 1     # извлечь 1 тендер (проверка, ~центы)
.venv/bin/python app.py extract               # все triaged relevant/gray
.venv/bin/python tools/view.py extractions
```
Дедуп форматов (pdf+docx одного файла = один документ), пропуск DUAE и стандартных форм.
Нарезка настраивается ключами extract.* (маркеры секций, пороги). Результат — таблица extractions.

## Фаза 4D: проверяющий (работник↔проверяющий)

Каждая аналитическая ступень идёт в паре с проверяющим (дешёвая модель), который сверяет
результат работника с исходным ТЗ: полнота (пропущенные поля — напр. valoare_estimata),
выдумки (нет ли лишнего), числа. По умолчанию строгий режим: при проблемах — повтор работника
с подсказкой; если не исправилось — флаг needs_review (для супер-агента, Фаза 7). Настраивается:
```
verify.strictness   strict | balanced | light   (по умолчанию strict)
verify.max_retries  1
```
Конвейер extract теперь = [extract, extract_verify]. Результаты: tools/view.py verifications.

ВАЖНО для существующей установки — обновить пайплайн (seed не перезаписывает):
```
python3 tools/config_cli.py set pipeline.tender_extract '["extract","extract_verify"]'
```

## Фаза 5: применимость (работник↔проверяющий)

Работник applicability берёт тендер + извлечённое ТЗ + ПОЛНЫЙ профиль компании (capabilities.profile)
и решает: can / partial / cannot + readiness_score (0-100) + reasoning + matched (что подошло) +
gaps (чего не хватает) + required_equipment (вход для Фазы 6). Релевантные → Sonnet, серая зона → Haiku.
Проверяющий applicability_verify сверяет вердикт с профилем (не сказал ли "можем" при дыре в gaps).

Профиль — свободная структура в конфиге, LLM рассуждает по всему содержимому. Правится под себя:
```
python3 tools/config_cli.py get capabilities.profile
python3 tools/config_cli.py set capabilities.profile '{...любые разделы и критерии...}'
```

```
.venv/bin/python app.py applicability --limit 1
.venv/bin/python tools/view.py applicability
```
Конвейер: collect → triage → extract(+verify) → applicability(+verify) → [Фаза 6: поставщики/маржа].

## Надёжность (после инцидента со stub)

- check и команды extract/applicability ГРОМКО предупреждают, если провайдер = stub
  (нет валидного ANTHROPIC_API_KEY) — чтобы битый ключ не маскировался под работу.
- Устойчивый разбор JSON (engine/jsonutil): снимает обёртки/преамбулу, вытаскивает {...}.
- Prefill: модель просят начинать ответ с "{" (чистый JSON).
- Честный fail: если ответ не распарсился — сырой текст сохраняется и тендер → needs_review,
  ничего не теряется (вместо пустого вердикта).

## Фаза 6: поставщики и маржа (каталог-приоритет)

По списку техники из извлечения/применимости подбираем поставщиков. Разделение по принципу
producer/verifier и "деньги считает код":
- LLM (suppliers) сопоставляет каждую позицию с КАТАЛОГОМ (suppliers.catalog) и оценивает
  соответствие спецификации (full/partial/none + confidence) — НЕ цены.
- КОД считает: line_cost = цена × количество, total, margin = (стоимость_тендера − total)/тендер.
- suppliers_verify сверяет: реально ли продукт отвечает спецификации, не выдумана ли потировка.

Каталог — в конфиге (правится под себя; дефолт содержит примеры Jenoptik/Cisco/Genetec):
```
python3 tools/config_cli.py get suppliers.catalog
python3 tools/config_cli.py set suppliers.catalog '[{"id":"...","supplier":"...","model":"...","price":2800,"currency":"EUR","specs":"..."}]'
```
Веб-добор (suppliers.web_enabled) — тумблер, пока заглушка (включим, когда добавим веб-поиск в шлюз).

```
.venv/bin/python app.py suppliers --limit 1
.venv/bin/python tools/view.py suppliers
```
Конвейер: ... → applicability(+verify) → suppliers(+verify) → [Фаза 7: супер-агент/дайджест].

## Фаза 6.1: корректная маржа (валюта + неполнота)

- Все цены каталога приводятся к валюте тендера по курсам suppliers.fx_rates
  (EUR->MDL и т.д., настраиваются; обратный курс считается автоматически).
- Если часть позиций не подобрана ИЛИ нет курса — маржа помечается неполной (margin_partial,
  в выводе '~' и колонка partial), и тендер уходит в needs_review. Чтобы 47% не выглядели как 97%.

Обнови курсы под себя:
```
python3 tools/config_cli.py set suppliers.fx_rates '{"EUR->MDL":19.6,"USD->MDL":18.0,"RON->MDL":3.9}'
```

## Фаза 7: супер-агент (дайджест + эскалация + полнота)

Слой НАД ступенями (не ступень конвейера). Делает три вещи:
- ДАЙДЖЕСТ: ранжирует тендеры can/partial по readiness_score + честная маржа
  (веса supervisor.rank_weights). Топ — то, что стоит брать.
- ЭСКАЛАЦИЯ: разбирает флаги needs_review. autonomy=auto (по умолчанию) — пограничную
  применимость сам переспрашивает у Opus и перепроверяет; suppliers-пробелы → всегда человеку.
  autonomy=advise — только помечает, ничего не тратит. Бюджет: supervisor.max_escalations.
- ПОЛНОТА: по source_runs ловит застой сбора, ошибки, резкое падение числа тендеров (анти-пропуск).

```
.venv/bin/python app.py digest              # только дайджест
.venv/bin/python app.py supervise           # эскалация + полнота + дайджест
python3 tools/config_cli.py set supervisor.autonomy '"advise"'   # консервативный режим
```
