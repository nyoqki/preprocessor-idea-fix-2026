# Ясно

Личный ИИ-тренажёр по математике в Сферуме. Команда "Что такое препроцессор", МБОУ-СОШ № 10, Орёл. Хакатон "Идея фикс", трек "Искусственный интеллект в школьных процессах".

Бот для проверки: [@ideya_fiks_159_bot](https://max.ru/ideya_fiks_159_bot).
Репозиторий: [preprocessor-idea-fix-2026](https://github.com/nyoqki/preprocessor-idea-fix-2026).
[Строгая вычитка и готовность к 20 баллам](docs/strict-review.md) · [Аудит по критериям хакатона](docs/hackathon-audit.md) · [Вычитка презентации и анкеты](docs/presentation-review.md).

Ученик присылает боту фото домашней работы. Бот распознаёт решение, находит шаг, на котором появилась ошибка, и объясняет её наводящим вопросом, не давая готового ответа. Ошибки складываются в личную карту пробелов. За два дня до контрольной бот сам пишет ученику и собирает тест по темам контрольной и по его собственным пробелам.

## Возможности

- Разбор фото решения: распознавание строк, пошаговая символьная проверка (SymPy), тип ошибки, подсказка без ответа и продолжение диалога.
- Личная карта пробелов с интервальным повторением.
- Контрольные: из сообщения ученика или из объявления в чате класса.
- Персональные тесты: задания генерируются с гарантированно верным ответом, неверные варианты - типичные ошибки самого ученика.
- Материалы класса: фото конспектов из чата класса распознаются и попадают в поиск.
- Мини-приложение: карта пробелов, история разборов с подсветкой ошибки на фото, тесты, материалы, экран учителя.
- Учителю еженедельная сводка по темам без имён и личных работ; единичные группы скрываются.

## Архитектура

| Компонент  | Назначение                                                         |
| ---------- | ------------------------------------------------------------------ |
| `api`      | FastAPI: webhook MAX, API мини-приложения, раздача мини-приложения |
| `worker`   | arq: обработка обновлений, разбор фото, напоминания по расписанию  |
| `postgres` | PostgreSQL 17 + pgvector                                           |
| `redis`    | очередь задач и короткоживущие состояния диалога                   |
| `caddy`    | HTTPS с автоматическим сертификатом (профиль `public`)             |

ИИ-провайдеры: Yandex AI Studio, GigaChat и любой сервис с OpenAI-совместимым API (DeepSeek, OpenRouter, локальные Ollama, llama.cpp, vLLM). Порядок задаётся в `AI_PROVIDER_ORDER`, при сбое запрос уходит следующему.

## Требования

- Docker 24+ с Compose v2
- Домен, указывающий на сервер, открытые порты 80 и 443
- Токен бота MAX, ключи Yandex AI Studio, GigaChat или OpenAI-совместимого сервиса

## Запуск через Docker Compose

```bash
git clone git@github.com:nyoqki/preprocessor-idea-fix-2026.git yasno
cd yasno
cp .env.example .env
# заполнить MAX_BOT_TOKEN, MAX_WEBHOOK_SECRET, DOMAIN, PUBLIC_BASE_URL,
# POSTGRES_PASSWORD, YANDEX_API_KEY, YANDEX_FOLDER_ID и/или GIGACHAT_CREDENTIALS
docker compose --profile public up -d --build
docker compose exec api yasno webhook set
```

Миграции базы применяются автоматически сервисом `migrate` перед стартом `api` и `worker`.

Пример технического демо на синтетических данных с Chat/Vision DeepSeek:

```bash
AI_PROVIDER_ORDER=openai
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-...
OPENAI_CHAT_MODEL=deepseek-flash
OPENAI_VISION_MODEL=deepseek-flash
OPENAI_VISION_THINKING=false
```

[Документация vision DeepSeek](https://api-docs.deepseek.com/guides/vision/). Для отдельного vision-сервиса укажите `OPENAI_VISION_BASE_URL` и `OPENAI_VISION_API_KEY`. Минимальный набор для проверки подключения — `tests/fixtures/vision_smoke`; он не заменяет проверку рукописных работ.

Локально через Ollama: `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_CHAT_MODEL=qwen3:8b`, `OPENAI_VISION_MODEL=qwen2.5vl:7b`, ключ не нужен.

## Сборка и запуск контейнера

Сборка образа:

```bash
docker build -t yasno .
```

Кнопки возврата в чат в Docker-сборке ведут к `ideya_fiks_159_bot`. Для другого бота передайте `--build-arg VITE_BOT_USERNAME=your_bot`; при разработке Vite задайте `VITE_BOT_USERNAME` в окружении.

Готовый образ публикуется в GitHub Container Registry:

```bash
docker pull ghcr.io/nyoqki/preprocessor-idea-fix-2026:latest
```

Запуск отдельных процессов из одного образа:

```bash
docker run --rm --env-file .env yasno migrate
docker run -d --name yasno-api --env-file .env -p 8000:8000 yasno api
docker run -d --name yasno-worker --env-file .env yasno worker
```

## Пример запуска через командную строку

```bash
$ docker run --rm --env-file .env yasno webhook info
bot: ideya_fiks_159_bot (365466262)
webhook: https://yasno.example.ru/webhook/max types=['message_created', 'message_callback', ...]
```

Команды `yasno`:

| Команда                           | Что делает                                            |
| --------------------------------- | ----------------------------------------------------- |
| `yasno api [--host H] [--port P]` | HTTP-сервер (webhook, API, мини-приложение)           |
| `yasno worker`                    | обработчик очереди и напоминаний                      |
| `yasno migrate [revision]`        | миграции базы данных                                  |
| `yasno webhook set\|delete\|info` | управление подпиской на события MAX                   |
| `yasno poll`                      | получение событий через long polling (для разработки) |
| `python -m yasno.ai.eval <папка>` | сравнение моделей распознавания на наборе фото        |

## Переменные окружения

| Переменная                                                               | Назначение                                                                                                                                         |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MAX_BOT_TOKEN`                                                          | токен бота MAX                                                                                                                                     |
| `MAX_WEBHOOK_SECRET`                                                     | секрет заголовка `X-Max-Bot-Api-Secret` (буквы, цифры, `_`, `-`)                                                                                   |
| `PUBLIC_BASE_URL`, `DOMAIN`                                              | публичный адрес сервиса                                                                                                                            |
| `DATABASE_URL`, `REDIS_URL`                                              | подключения (в Compose задаются автоматически)                                                                                                     |
| `AI_PROVIDER_ORDER`                                                      | порядок провайдеров, например `yandex,gigachat`                                                                                                    |
| `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`                                     | доступ к Yandex AI Studio                                                                                                                          |
| `YANDEX_CHAT_MODEL`, `YANDEX_VISION_MODEL`, `YANDEX_OCR_MODEL`           | модели Yandex                                                                                                                                      |
| `GIGACHAT_CREDENTIALS`, `GIGACHAT_SCOPE`, `GIGACHAT_MODEL`               | доступ к GigaChat                                                                                                                                  |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_CHAT_MODEL`                 | OpenAI-совместимый сервис для текста                                                                                                               |
| `OPENAI_JSON_MODE`                                                       | `object`, `schema` или `off` — как запрашивать JSON у модели                                                                                       |
| `OPENAI_REASONING_TOKENS`                                                | дополнительный запас токенов для моделей с рассуждениями, чтобы содержательный ответ не обрезался                                                  |
| `OPENAI_VISION_THINKING`                                                 | `false` — распознавать фото без рассуждений (`thinking: disabled`, DeepSeek): быстрее и не упирается в лимит; не задано — параметр не отправляется |
| `OPENAI_VISION_MODEL`, `OPENAI_VISION_BASE_URL`, `OPENAI_VISION_API_KEY` | модель для распознавания фото, можно на другом сервисе                                                                                             |
| `AI_FAKE`                                                                | `true` — детерминированные заглушки вместо ИИ (разработка)                                                                                         |

Полный список — в `src/yasno/config.py`.

## Разработка

```bash
uv sync
uv run yasno migrate
uv run yasno poll &
uv run yasno worker
```

Проверки:

```bash
uv run ruff format --check
uv run ruff check
uv run mypy
TEST_DATABASE_URL=postgresql+asyncpg://user@localhost/yasno_test uv run pytest
```

Мини-приложение:

```bash
cd webapp
npm ci
npm run dev:mock
```

Зависимости Python зафиксированы в `uv.lock`; `requirements.txt` генерируется командой
`uv export --no-annotate --locked --no-dev --no-hashes --no-emit-project --no-header --format requirements-txt -o requirements.txt`.

## Данные

Фото работ и карта пробелов содержат персональные данные ребёнка. Для школьного пилота используйте согласованный контур обработки и провайдера; одно нажатие кнопки согласия не подтверждает выполнение всех требований к обработке данных детей.

Перед обработкой бот запрашивает согласие; пользователь, указавший возраст до 14 лет, получает ссылку для родителя. Собственное подтверждение по этой ссылке отклоняется, но возраст и родство сервис не удостоверяет. Материалы из общего чата обрабатываются только от подключённых участников с согласием.

Учитель видит количества по темам без имён и личных работ. Единичные группы скрываются; это не гарантия полной анонимности. Права администратора или владельца чата проверяются при подключении, каждом запросе сводки и перед недельным уведомлением; бот также должен быть администратором чата.

Команда `/delete` удаляет фото домашних работ, разборы, карту пробелов, тесты, личные контрольные, записи уведомлений и память личного диалога. Профиль аккаунта и общие материалы класса сохраняются.
