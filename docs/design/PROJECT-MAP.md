# Карта проекта и контекст дизайна

Снимок на 6 ноября 2026. Назначение — передать дизайнеру/Codex реальную структуру «Ясно», границы функциональности и точки изменений. Основной промпт — [PROMPT.md](PROMPT.md).

## Архитектура

```text
MAX / учебное пространство Сферум
  ├── Личный чат с ботом
  │     ├── класс, согласие, фото, уточнения, диалог
  │     ├── тесты и напоминания
  │     └── кнопки startapp → mini app
  ├── Чат класса → объявления и фото материалов
  └── Mini app: React + MAX UI
        └── /api/v1 → FastAPI
              ├── PostgreSQL: работы, темы, ошибки, тесты, классы
              └── storage: фото

Webhook MAX → FastAPI → Redis/arq → worker
  ├── bot routing и handlers
  ├── services: разбор, прогресс, тесты, материалы
  ├── AI: распознавание, объяснение, контекст
  ├── math/SymPy: проверка шагов и генераторы
  └── scheduler: напоминания и сводка учителю
```

API раздаёт production SPA, собранную в `webapp/dist`. Caddy обеспечивает HTTPS. Docker Compose поднимает API, worker, PostgreSQL с pgvector, Redis, миграции и опциональный Caddy. Наличие pgvector не означает, что каждый поиск уже использует эмбеддинги.

## Корень и поставка

| Путь | Роль |
|---|---|
| `README.md` | Продукт, возможности, запуск, конфигурация, данные |
| `pyproject.toml`, `uv.lock`, `requirements.txt`, `.python-version` | Python 3.13, зависимости, типизация, линтер, pytest |
| `Dockerfile` | Сборка frontend и Python-приложения |
| `compose.yaml` | Сервисы API/worker/migrate/PostgreSQL/Redis/Caddy |
| `deploy/Caddyfile` | HTTPS и reverse proxy |
| `.env.example` | Пример конфигурации; реальные секреты не нужны для дизайна |
| `.github/workflows/ci.yml` | Python-проверки, frontend lint/typecheck/build, сборка образа |
| `alembic.ini`, `src/yasno/db/migrations/` | Миграции базы |
| `webapp/` | Единственный web-интерфейс; здесь будет основная работа по дизайну |
| `src/yasno/` | Backend, bot, worker, математика и AI |
| `tests/` | Тесты backend и сценариев бота |

При начале исследования уже были незакоммиченные изменения в README, примере env, AI-конфигурации/провайдерах, математической проверке и соответствующих тестах. Они не относятся к этому заданию и не должны перезаписываться. Исследование добавляет только `docs/design/`.

## Frontend: все исходные модули

| Путь в `webapp/` | Назначение и значение для дизайна |
|---|---|
| `package.json`, `package-lock.json` | React 19.2.8, MAX UI 0.9.0, TypeScript, Vite; зафиксированная база |
| `vite.config.ts`, `tsconfig*.json`, `eslint.config.js`, `.npmrc` | Сборка, dev proxy и проверки |
| `index.html`, `public/favicon.svg` | Entry point, Bridge script и иконка |
| `src/main.tsx` | Импорт MAX UI CSS перед собственным CSS, StrictMode |
| `src/Root.tsx` | Provider `MaxUI`, colorScheme и platform |
| `src/App.tsx` | Профиль, выбор экрана, auth, offline banner, вкладки, BackButton |
| `src/router.ts` | Hash routes, родительские страницы, tab selection, startapp |
| `src/max.ts` | Bridge-обёртка: initData, platform, ready, haptics, BackButton, openLink |
| `src/hooks.ts` | Загрузка данных, debounce, тема ОС, online |
| `src/styles.css` | 1155 строк на момент исследования; собственные токены и стили всех экранов |
| `src/format.ts` | Склонения, даты и общие сообщения об ошибках |
| `src/status.ts` | Краткие статусы разбора; сейчас недостаточно учитывают verdict |
| `src/api/types.ts` | Источник frontend-типов и допустимых состояний |
| `src/api/client.ts` | HTTP API, `Authorization: tma`, таймаут, retry, ошибки |
| `src/api/index.ts` | Выбор mock по `VITE_MOCK === "1"` |
| `src/api/mock.ts` | Демо-карта, работы, тест №7, материалы и профиль учителя |
| `src/ui/common.tsx` | Screen/Header, Skeleton, EmptyState, ErrorState, Chip |
| `src/ui/TabBar.tsx` | Карта/Разборы/Класс и условно Учитель |
| `src/ui/icons.tsx` | Существующий набор SVG-иконок |
| `src/screens/GapMap.tsx` | Карта, summary, CTA активного теста, темы |
| `src/screens/Submissions.tsx` | История, статусы и пагинация |
| `src/screens/SubmissionDetail.tsx` | Фото, bbox, строки, результат и подсказка |
| `src/screens/Quiz.tsx` | Вопрос, отправка, feedback, переход, итог |
| `src/screens/ClassMaterials.tsx` | Поиск, snippets, отсутствие класса, пагинация |
| `src/screens/Teacher.tsx` | Сводка класса и распределение статусов |

MAX UI уже используется для `Button`, `Typography`, `CellList`, `CellSimple`, `Input`, `Spinner`. Большая часть доменного оформления написана вручную. Установленный kit также содержит другие компоненты, включая BottomSheet; доступность и соответствие API нужно проверять по его `.d.ts` и реализации, а не предполагать по названию.

## Навигация и контракты

| Hash route | Экран | API |
|---|---|---|
| `#/map` / корень | Карта | `GET /me`, `/gaps`, `/quizzes/active` |
| `#/submissions` | История | `GET /submissions?cursor=...` |
| `#/submissions/:id` | Разбор | `GET /submissions/:id`, image URL из ответа |
| `#/quiz/:id` | Тест и итог | `GET /quizzes/:id`, `POST /quizzes/:id/items/:itemId/answer` |
| `#/class` | Материалы | `GET /materials?q=...&cursor=...` |
| `#/teacher` | Учитель | `GET /teacher/summary` |

В таблице API указан относительно `/api/v1`. Из bot `startapp` поддерживаются `map/gaps`, `submissions/history`, `class/materials`, `teacher`, `submission_<id>`, `quiz_<id>`. Прямой вход в вложенную страницу должен работать без предыдущего посещения карты.

### Какие данные реально доступны

- **Профиль:** имя, `student/teacher`, класс обучения, согласие, привязанный школьный класс. Нет API списка всех школьных организаций и автоматического импорта ролей Сферума.
- **Темы:** статус `weak/improving/solid`, накопленные правильные/неправильные попытки, дата последней ошибки и следующего повторения, типы ошибок. Нет временного ряда для диаграммы прогресса по неделям.
- **Разбор:** технический статус и отдельный verdict, фото, условие, строки Unicode/LaTeX, confidence, bbox, первая ошибка, подсказка. Нет frontend endpoint загрузки фото или исправления распознанных строк: это bot-сценарий.
- **Тест:** reason, status, количество вопросов и ответов, варианты, результат ранее отвеченных вопросов. До ответа correct index не выдаётся. POST возвращает проверенный результат, explanation и сведения о повторной отправке.
- **Материалы:** название, выдержка, темы, дата, курсор и `has_class`. Нет API полного материала/скачивания/URL исходного сообщения.
- **Учитель:** класс, число учеников и учеников с темами для повторения, распределения по темам и частые ошибки. Нет имён и индивидуальных работ. Не все маленькие агрегаты отфильтрованы.

### Состояния, которые нельзя смешивать

| Уровень | Значения | Интерпретация |
|---|---|---|
| `SubmissionStatus` | queued, processing, needs_confirmation, done, failed | Жизненный цикл обработки |
| `Verdict` анализа | correct, error, incomplete, review; также ошибки распознавания | Смысл результата; `done` само по себе не означает «верно» |
| `GapStatus` | weak, improving, solid | Состояние темы по накопленным попыткам |
| `QuizStatus` | active, completed, expired | Можно ли продолжать тест |
| `QuizReason` | exam, review, manual | Почему создана тренировка |
| `ConsentStatus` | none, pending, granted, revoked | Согласие, не роль пользователя |
| Ошибки клиента | auth, forbidden, not_found, network, server, client | Восстановление зависит от причины |

## Backend: карта всех подсистем

### HTTP — `src/yasno/api/`

`app.py` собирает приложение, middleware и routers; `deps.py` даёт settings/session/queue; `health.py` — liveness/readiness; `webhook.py` принимает события MAX и ставит задания в очередь.

`webapp/auth.py` проверяет подпись/срок initData, создаёт current user, проверяет роль teacher и выдаёт подписанные media tokens. `schemas.py` описывает выходные данные; `common.py` — курсоры, типы и display math; `profile.py` — профиль/карта; `submissions.py` — собственные работы и изображения; `quizzes.py` — тесты и ответы; `materials.py` — поиск по названию/тексту; `teacher.py` — агрегаты; `spa.py` — static/SPA и заголовки безопасности.

### Бот — `src/yasno/bot/`

`app.py` собирает routes; `routing.py` направляет updates; `context.py` хранит зависимости; `common.py` — reply и клавиатуры; `links.py` — ссылки start/startapp; `memory.py` — контекст диалога; `texts.py` — все основные сообщения и подписи.

Handlers:

- `start.py`: onboarding, 8–11 класс, согласие, родительская ссылка, подключение по приглашению, удаление данных.
- `homework.py`: фото, лимиты, распознавание, уточнение строк, результат и продолжение диалога.
- `dialog.py`: объявления о контрольных и свободные вопросы.
- `quiz.py`: запуск тестов в чате, варианты, результат, повторная отправка.
- `group.py`: подключение бота к классу, объявления и ingestion фото материалов. Учебные ответы в общий чат не отправляются.

### Продуктовые сервисы — `src/yasno/services/`

`analysis.py` сохраняет фото, распознаёт, проверяет и формирует verdict; `progress.py` записывает ошибки/успехи и интервалы повторения; `quizzes.py` планирует темы, генерирует задания и сохраняет ответы; `materials.py` распознаёт материалы и ищет релевантный текст; `exams.py` — события контрольных; `classes.py` — приглашения и классы; `consent.py` — согласие и удаление; `notifications.py` — учёт рассылки.

Прогресс считается по коробкам повторения с интервалами 2/4/7/14 дней; это логика сервиса, а не готовый процент знания предмета. Персональную карту формируют темы, где уже были ошибки. Нулевое число тем в карте не доказывает знание всей программы.

Поиск материалов mini app сейчас использует `ILIKE` по title/content. Подбор материалов для диалога использует PostgreSQL full-text search на русском. Существование pgvector/Embedder в архитектуре не даёт оснований подписывать текущий UI «семантический поиск». Генератор теста использует темы и типичные ошибки, а не полный контент конспектов как обязательный вход в `build_quiz`.

### Worker — `src/yasno/worker/`

`app.py` создаёт зависимости и обрабатывает queued updates. `reminders.py` содержит напоминания о контрольных/повторении и недельный digest учителю. У digest `MIN_GROUP_FOR_DIGEST = 2`; в HTTP-сводке аналогичного ограничения нет. Сам по себе этот порог не является доказательством полной анонимности.

### AI — `src/yasno/ai/`

`types.py` — протоколы/структуры; `registry.py` — сборка провайдеров; `http.py` — HTTP/usage; `resilience.py` — timeout/retry/fallback/circuit breaker. `yandex.py`, `gigachat.py`, `openai_compat.py` — реализации; `fakes.py` — детерминированные заглушки.

`tutor.py` — подсказки, темы, контрольные и ответы; `prompts.py` — продуктовая персона, распознавание и ограничения готового ответа; `transcription.py`, `parsing.py`, `matching.py`, `latex.py` — разбор и выравнивание строк; `exams.py` — даты/объявления; `eval.py` — оценка распознавания на наборах фото.

### Математика — `src/yasno/math/`

`topics.py`, `errors.py` — словарь тем и ошибок; `display.py` — отображение Unicode; `parsing.py` — строки и математические сущности; `verification.py` — структура результата; `verify.py` и `checkers.py` — проверка; `solving.py`, `equivalence.py` — решение/сравнение; `mistakes.py` — типичные ошибочные преобразования; `leak.py` — обнаружение раскрытия ответа; `limits.py` — ограничения вычислений.

`generators/`: `base.py`, `arithmetic.py`, `algebra.py`, `equations.py`, `inequalities.py`, `calculus.py`, `__init__.py` — генерация заданий и дистракторов. Эти алгоритмы не следует менять ради оформления. Для неподдерживаемых случаев существует мягкий `review`, который нельзя показывать как уверенное «верно».

### Данные и инфраструктура

`db/models.py` содержит классы/пользователей, работы, ошибки, прогресс, контрольные, тесты/вопросы, материалы и уведомления. `db/base.py`, `session.py`, migrations — инфраструктура БД. `storage.py`, `media.py` — файлы, ключи и форматы. `max/client.py`, `types.py`, `keyboard.py`, `tls.py`, `certs/` — MAX API, типы и транспорт. Корневые `config.py`, `cli.py`, `clock.py`, `logs.py`, `queue.py`, `polling.py`, `security.py`, `users.py` — настройки и запуск.

## Тесты и проверки

| Папка | Что уже описано тестами |
|---|---|
| `tests/api/` | initData, роли, доступ к чужим работам, изображения, SPA, поиск, тесты и пагинация |
| `tests/bot/` | onboarding, согласие родителя, фото, исправления, quiz, объявления, материалы, routing |
| `tests/services/` | Интервалы повторения и статусы тем |
| `tests/worker/` | Напоминания, дедупликация и порог digest |
| `tests/ai/` | Провайдеры, парсинг, resilience, tutor, OCR и eval |
| `tests/math/` | Проверка, генераторы, отображение, parsing, leak и limits |
| `tests/max/`, `tests/test_security.py` | Клиент MAX, TLS, типы и подписи |

В `webapp/package.json` нет отдельного browser-test script; есть lint/typecheck/build. Визуальная проверка должна быть добавлена как процесс, а не объявлена уже существующей тестовой системой.

Проверенные команды исследования:

```bash
cd /home/jiraya/Projects/yasno/webapp
VITE_MOCK=1 npm run dev:mock
```

Маршруты демо: `#/map`, `#/submissions`, `#/submissions/41`, `#/quiz/7`, `#/class`, `#/teacher`. Изображения тетради в mock — синтетические SVG, не реальные работы детей.

## Объём следующего этапа

Основные изменения: дизайн-токены, `styles.css`, общие UI-компоненты, шесть экранов, редактура `format.ts/status.ts`, обработка состояния и тем. Существующие API/маршруты сохраняются. Любые правки server-side приватности выделяются отдельно и проверяются целевыми тестами. Вопросы математики и AI-провайдеров не включаются в визуальный рефакторинг автоматически.
