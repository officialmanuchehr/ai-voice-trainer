# AI Voice Trainer — ядро MVP (Банк Эсхата)

Голосовой AI-тренажёр клиентских менеджеров. Нерушимый принцип: LLM никогда не
является источником продуктовой правды — правда живёт только в базе знаний
(`seed/knowledge_base.json` → БД). Подробности — в промптах провайдеров
(будут добавлены в БЛОКЕ 1–3).

## Статус

БЛОК 0 — каркас: готово.
БЛОК 1 — текстовый + голосовой диалог с AI-клиентом (DeepSeek + ElevenLabs TTS):
готово, тесты на анти-галлюцинацию пройдены.
БЛОК 2 — реальная транскрибация (Deepgram nova-3), `/sessions/{id}/voice-turn`,
`/sessions/{id}/transcript`, аудио никогда не пишется на диск: готово.
БЛОК 3 — ScoringProvider на Claude Sonnet 5 (claim-verification + оценка по
рубрике), `POST /sessions/{id}/finish`, экран результата: готово. Гейт-тест
на мисселинг пройден (итог не выше 60, критичные ошибки зафиксированы).
Ядро MVP по ТЗ завершено полностью.

## Стек

- FastAPI (async) + SQLAlchemy (async) + SQLite (`aiosqlite`)
- Провайдеры STT/Dialog/Scoring/TTS — за интерфейсами (`app/providers/base.py`),
  выбор реализации через переменные окружения `*_PROVIDER`.

## Установка и запуск

```bash
cd /Users/manuchehr/Desktop/ai-voice-trainer

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# заполнить DEEPGRAM_API_KEY, DEEPSEEK_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
# и выставить STT_PROVIDER=deepgram, DIALOG_PROVIDER=deepseek, TTS_PROVIDER=elevenlabs

uvicorn app.main:app --reload --port 8000
```

Открыть в браузере: `http://127.0.0.1:8000/` — одна HTML-страница с контекстом
сценария, чатом и озвучкой ответов AI-клиента.

Сервер поднимется на `http://127.0.0.1:8000`. При старте (`lifespan`) таблицы
создаются автоматически (`create_all`), после чего в БД загружается seed:
продукт `merchant_onboarding`, срез базы знаний версии `1.0.0` и сценарий
`scn_merchant_onboarding_medium_01`.

## Проверка

```bash
# 1. Health-check
curl -s http://127.0.0.1:8000/health
# ожидание: {"status":"ok"}

# 2. Продукт загружен в БД
curl -s http://127.0.0.1:8000/products
# ожидание: [{"id":"merchant_onboarding","name":"...","segment":"..."}]

# 3. Факты из базы знаний загружены (approved_facts, objections, forbidden и т.д.)
curl -s http://127.0.0.1:8000/kb/merchant_onboarding | python3 -m json.tool

# 4. Сценарий по умолчанию загружен
curl -s http://127.0.0.1:8000/scenarios | python3 -m json.tool

# 5. Создать сессию
curl -s -X POST http://127.0.0.1:8000/sessions -H "Content-Type: application/json" \
  -d '{"scenario_id":"scn_merchant_onboarding_medium_01"}'

# 6. Реплика менеджера -> ответ AI-клиента (ID сессии из шага 5)
curl -s -X POST http://127.0.0.1:8000/sessions/<SESSION_ID>/turns \
  -H "Content-Type: application/json" -d '{"text":"Добрый день!"}'

# 7. Озвучка последней реплики клиента (turn_index из ответа шага 6)
curl -s -o reply.mp3 http://127.0.0.1:8000/sessions/<SESSION_ID>/turns/<TURN_INDEX>/audio

# ⚠️ ТЕСТ НА АНТИ-ГАЛЛЮЦИНАЦИЮ (гейт Блока 1): AI-клиент НЕ должен подтвердить
# лимит 500 000 (в БЗ — 100 000).
curl -s -X POST http://127.0.0.1:8000/sessions/<SESSION_ID>/turns \
  -H "Content-Type: application/json" \
  -d '{"text":"У вас лимит снятия 500 000 сомони без комиссии, верно?"}'

# 8. Голосовой раунд: аудио -> STT (Deepgram) -> DialogProvider -> TTS
curl -s -X POST http://127.0.0.1:8000/sessions/<SESSION_ID>/voice-turn \
  -F "audio=@turn.wav;type=audio/wav"
# ответ: {"manager_turn_index":..,"manager_text":"<распознанный текст>",
#         "ai_client_turn_index":..,"ai_client_text":"...","ai_client_audio_base64":"..."}

# 9. Полный транскрипт сессии
curl -s http://127.0.0.1:8000/sessions/<SESSION_ID>/transcript | python3 -m json.tool
```

Прямая проверка файла БД (сервер должен быть остановлен, либо открывать read-only):

```bash
sqlite3 data/app.db "select id, name, segment from products;"
sqlite3 data/app.db "select id, product_id, version from knowledge_base;"
sqlite3 data/app.db "select id, product_id, difficulty, rubric_id from scenarios;"
```

## Структура проекта

```
app/
  main.py             # FastAPI: /, /health, /products, /kb, /scenarios, /sessions,
                       # /sessions/{id}/turns, /sessions/{id}/voice-turn,
                       # /sessions/{id}/transcript, /sessions/{id}/turns/{i}/audio
  config.py           # Settings из .env (DATABASE_URL, *_PROVIDER, ключи, DEEPSEEK_MODEL)
  database.py         # async engine/session, Base
  models.py           # products, knowledge_base, scenarios, sessions, transcript_turns,
                       # claim_checks, scores, feedback
  seed_loader.py       # читает seed/*.json, пишет в БД при старте
  prompts.py          # Промпт A (системный промпт AI-клиента), сборка из
                       # client_profile сценария + approved_facts/objections БЗ
  constants.py        # словарь банковских терминов (keyterms) для STT
  providers/
    base.py           # абстрактные интерфейсы STT/Dialog/Scoring/TTS
    stub.py           # заглушки (Scoring — пока не реализован по-настоящему)
    factory.py        # выбор реализации провайдера по env
    deepseek_dialog.py   # DialogProvider на DeepSeek (chat/completions)
    elevenlabs_tts.py    # TTSProvider на ElevenLabs (text-to-speech)
    deepgram_stt.py      # STTProvider на Deepgram nova-3 (ru, keyterm prompting)
static/
  index.html          # единственная HTML-страница (без сборки): чат, контекст
                       # сценария, воспроизведение озвученных ответов
seed/
  knowledge_base.json
  rubric.json
  scenarios.json
tests/fixtures/
  dialogue_honest.json           # честный диалог (эталон для регрессионных прогонов оценщика)
  dialogue_misselling_500k.json  # диалог с мисселингом: неверный лимит (500k) + "одобрение гарантировано"
data/
  app.db             # создаётся автоматически при первом запуске
.env.example
requirements.txt
```

## Модель данных

`products → scenarios → sessions → transcript_turns / claim_checks / scores / feedback`,
плюс `knowledge_base` — неизменяемый снимок БЗ по версии (`kb_version`),
на который ссылается `sessions.kb_version`, чтобы результат тренировки был
навсегда привязан к версии контента, на котором она проходила.

## Провайдеры

Выбор реализации — через `.env`:

```
STT_PROVIDER=stub|deepgram
DIALOG_PROVIDER=stub|deepseek
SCORING_PROVIDER=stub|claude
TTS_PROVIDER=stub|elevenlabs
```

Сейчас реально подключены все четыре: `STT_PROVIDER=deepgram`,
`DIALOG_PROVIDER=deepseek` (модель по умолчанию `deepseek-chat`, которая на
данный момент указывает на DeepSeek V4 Flash), `TTS_PROVIDER=elevenlabs`,
`SCORING_PROVIDER=claude` (модель `claude-sonnet-5`, официальный SDK
`anthropic`).

## Оценка (Блок 3)

`POST /sessions/{id}/finish` — два последовательных вызова Claude Sonnet 5:

1. **Claim-verification** (промпт B) — сверяет каждое продуктовое утверждение
   менеджера с `approved_facts`, `approved_arguments` и `approved_response`
   каждого возражения из БЗ (снимка, привязанного к `session.kb_version`).
   Вердикт `approved|unapproved|forbidden` сохраняется в `claim_checks`.
2. **Оценка** (промпт C) — получает вердикты пасса 1 как готовый факт и
   выставляет баллы по `rubric_sales_100`, не решая заново, что было
   мисселингом. Любой `unapproved`/`forbidden` — критичная ошибка, обнуляющая
   соответствующий критерий и капающая итог на 60. Сохраняется в `scores` +
   `feedback`.

JSON-ответ модели парсится с retry (до 3 попыток) на случай невалидного JSON
или markdown-обёртки. `max_tokens=8192` — на Sonnet 5 adaptive thinking
включён по умолчанию и тоже расходует лимит токенов; на полном промпте
(рубрика + транскрипт) 4096 токенов недостаточно и обрезает ответ ещё на
стадии рассуждения, до текстового блока.

### Стабилизация оценки

Три прогона одного и того же честного диалога подряд показали разброс между
прогонами (особенно `objections`: 0/10 vs 6/10, `no_misselling`: 5/10 vs 9/10).
Исправлено:

1. **`total` считает не модель, а Python** (`ClaudeScoringProvider._finalize_total`)
   — сумма `breakdown[].score`, и если есть хоть один `unapproved`/`forbidden`
   claim или критичная ошибка — `min(сумма, 60)`. Модель JSON с `total` больше
   не возвращает.
2. **Явная таблица «тип критичной ошибки → какой ровно один критерий
   обнулять»** в промпте C (`rubric.critical_error_criterion_map` в
   `seed/rubric.json`, отрисовывается в промпт через `_format_critical_error_map`
   в `app/prompts.py`) — раньше модель сама решала, произвольно зануляя то один,
   то сразу два критерия за одну и ту же ошибку.
3. **`critical_errors[].type` ограничен enum'ом** через `output_config.format`
   (structured output, JSON Schema) — допустимые значения берутся из
   `rubric.critical_errors`, модель не может изобретать свободные формулировки.
4. **Числовые якоря по каждому критерию** в `seed/rubric.json`
   (`criteria[].anchors`: 8-10 образцово / 4-7 есть пробелы / 0-3 грубые
   нарушения, с адаптацией шкалы под `max` каждого критерия).

После фикса три прогона того же диалога дали `objections` и `no_misselling`
идентично (9/10 во всех трёх), сырую сумму без капа — 73-75 (было 66-72).
`needs` остаётся немного нестабильным (10-12/15) — это уже не баг агрегации,
а обычный шум LLM-суждения; не тронуто в рамках этой правки (эффорт/
self-consistency — сознательно отложены).

### Детерминированный гейт-тест (`tests/run_gate_test.py`)

Прогон фикстуры через `POST /sessions/{id}/turns` каждый раз даёт новый
транскрипт — реплики AI-клиента генерирует DialogProvider заново, поэтому
такой прогон непригоден как регрессионный тест оценщика (он проверяет заодно
и диалог, и оценку, смешивая источники нестабильности).

`tests/run_gate_test.py` вместо этого пишет транскрипт фикстуры (обе роли,
`manager` и `ai_client`) напрямую в `transcript_turns` через SQLAlchemy —
DialogProvider не импортируется и не вызывается вообще. Затем скрипт
дёргает только `POST /sessions/{id}/finish` по HTTP. Так тест детерминирован
на входе и проверяет исключительно ScoringProvider.

```bash
python3 tests/run_gate_test.py tests/fixtures/dialogue_honest.json
python3 tests/run_gate_test.py tests/fixtures/dialogue_misselling_500k.json
# опционально: -o <путь> — куда сохранить полный JSON-результат /finish
```

Сервер (`uvicorn`) должен быть запущен — скрипт пишет в тот же SQLite-файл,
что использует сервер (`DATABASE_URL` из `.env`), и обращается к нему по HTTP
только за `/finish`.

## Голос

- **Вывод (TTS)** — ElevenLabs, ответ AI-клиента озвучивается и воспроизводится
  в браузере автоматически.
- **Ввод (STT)** — Deepgram nova-3, `ru`, с словарём банковских терминов
  (`app/constants.py`: РКО, эквайринг, зарплатный проект, оборотные средства,
  комиссия, терминал, расчётный счёт, Эсхата Онлайн, сомони, торговец, кошелёк),
  передаётся через `keyterm`-параметры запроса. Кнопка push-to-talk на странице
  теперь работает: запись через `MediaRecorder`, отправка на `/voice-turn`.

## Гарантия: аудио никогда не попадает на диск

`POST /sessions/{id}/voice-turn` обрабатывает аудио полностью в памяти:
байты читаются из загруженного файла, передаются в Deepgram HTTP-запросом
напрямую (`await audio.read()` → `stt_provider.transcribe(...)`), после чего
переменная с байтами удаляется (`del audio_bytes` в `finally`). Ни в одной
точке кода нет операции записи файла на диск и нет колонки для хранения
аудио/BLOB в БД (см. `app/models.py`).

Проверить это можно так:

```bash
# Код: убедиться, что в app/ нет ни одной операции записи файла
grep -rniE "open\(.*['\"]w|namedtemporaryfile|tempfile|\.save\(|shutil\.copy|mkstemp" app/
# ожидание: пусто (grep ничего не найдёт)

# Схема БД: подтвердить отсутствие BLOB/audio-колонок
sqlite3 data/app.db ".schema" | grep -iE "audio|blob"
# ожидание: пусто

# Runtime-проверка после реального голосового запроса:
touch /tmp/marker
curl -s -X POST http://127.0.0.1:8000/sessions/<SESSION_ID>/voice-turn -F "audio=@turn.wav;type=audio/wav" -o /dev/null

find /Users/manuchehr/Desktop/ai-voice-trainer /tmp "$TMPDIR" -newer /tmp/marker \
  \( -iname "*.wav" -o -iname "*.mp3" -o -iname "*.webm" -o -iname "*.ogg" -o -iname "*.aiff" -o -iname "*.m4a" \) 2>/dev/null
# ожидание: пусто — ни одного нового аудиофайла нигде

lsof -p $(pgrep -f "uvicorn app.main:app") | grep -Ei "\.wav|\.mp3|\.webm|\.ogg|\.aiff|\.m4a"
# ожидание: пусто — процесс не держит открытым ни одного аудиофайла

ls -la data/
# ожидание: только app.db
```

## Гейт-тест Блока 3 (пройден)

Прогнаны два диалога:
- `tests/fixtures/dialogue_honest.json` — менеджер называет только факты из БЗ
  (плюс одна собственная импровизация про отчётность/кассу, которой нет в
  БЗ — корректно поймана как unapproved). Итог: 60 (капнут одной реальной
  ошибкой), большинство claim'ов — approved.
- `tests/fixtures/dialogue_misselling_500k.json` — менеджер дважды называет
  неверный лимит (500 000 вместо 100 000) и заявляет «одобрение
  гарантировано». Итог: 6/100. 6 критичных ошибок. В фидбэке — точные цитаты
  и фраза «Эта формулировка не засчитана как корректная, потому что такого
  условия нет в утверждённой базе знаний».

Ядро MVP по исходному ТЗ (Блоки 0–3) полностью реализовано.

## Деплой на Railway (внутренний тест)

Файлы: `Dockerfile`, `railway.json`, `.dockerignore`.

**Что поменялось для деплоя (только конфиг, код провайдеров/бизнес-логики не тронут):**

- `DATABASE_URL` теперь поддерживает Postgres: `app/config.py` автоматически
  переписывает `postgres://`/`postgresql://` в `postgresql+asyncpg://`, так что
  сырой URL из плагина Railway Postgres можно вставить как есть.
- Добавлен `asyncpg` в `requirements.txt` (SQLite/`aiosqlite` остаётся для
  локальной разработки — оба драйвера сосуществуют, выбор через `DATABASE_URL`).
- Добавлен `app/auth.py` — HTTP Basic Auth на всё приложение (кроме `/health`,
  чтобы платформенный healthcheck Railway проходил без учётных данных). Пусто
  в `BASIC_AUTH_USERNAME`/`BASIC_AUTH_PASSWORD` = auth выключен (локальный
  дефолт); на Railway оба переменные обязательны.

**Проверено вручную** (Docker + одноразовый контейнер `postgres:16-alpine`,
без Railway): приложение стартует на пустом Postgres, `create_all` создаёт
все 8 таблиц, `load_seed` заполняет `products`/`knowledge_base`/`scenarios`;
повторный старт на уже заполненной БД не падает и не дублирует строки
(upsert-логика `seed_loader.py` не менялась); Basic Auth: без креденшлов —
401, с неверными — 401, с верными — 200, `/health` — 200 без креденшлов всегда.

Пошаговая инструкция по Railway — в чате с ассистентом / у того, кто настраивал деплой.
