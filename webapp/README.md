# Mini app «Ясно»

React 19 + TypeScript + Vite + MAX UI 0.9.0. API `/api/v1`, существующая авторизация MAX и hash routes сохранены.

```bash
npm ci
npm run dev:mock
```

- Приложение: <http://localhost:5173/#/map>
- Каталог компонентов и состояний: <http://localhost:5173/?catalog=1>
- Учитель в демо: <http://localhost:5173/?role=teacher#/teacher>
- Тёмная тема в демо: <http://localhost:5173/?theme=dark#/map>

По умолчанию демо показывает ученика с тремя вкладками. Каталог позволяет выбрать роль, тему, сценарий и экран. Ответы демо живут только в sessionStorage текущей вкладки; в каталоге есть сброс. Данные синтетические.

`npm run dev` работает с настоящим HTTP-клиентом; Vite перенаправляет `/api` на `http://127.0.0.1:8000` или `YASNO_API`. В production всегда используется HTTP API, даже если окружение содержит `VITE_MOCK=1`. Служебный каталог, роли и сценарии в production не работают.

Необязательная публичная build-переменная `VITE_BOT_USERNAME` включает кнопку «Открыть чат». Без неё приложение показывает инструкцию возврата в личный чат с ботом. Секреты и bot token во frontend не нужны.

```bash
npm run lint
npm run typecheck
npm run build
npm run test:browser
```

Браузерная проверка использует `playwright-core` и системный Chromium (`/usr/bin/chromium`). При другом пути задайте `CHROMIUM_PATH`. Команда сама запускает два временных Vite на 5183/5184 и завершает их после проверки. Для уже запущенных стендов доступны `YASNO_DEMO_URL` и `YASNO_HTTP_URL`. Скриншоты и отчёт сохраняются в `docs/design/evidence/implementation/`.

HTTP-сценарии тестов подменяют ответы API на уровне браузера. Они проверяют настоящий frontend HTTP-клиент, но не заменяют интеграционные тесты FastAPI/PostgreSQL. Нативные кнопки и viewport дополнительно проверяются с тестовым Bridge; реальный MAX остаётся отдельной проверкой.

[Дизайн-система](../docs/design/SYSTEM.md) · [Словарь](../docs/design/COPY.md) · [Матрица состояний](../docs/design/STATE-MATRIX.md) · [Проверка](../docs/design/QA.md) · [Скриншоты](../docs/design/SCREENSHOTS.md) · [Серверная приватность](../docs/design/PRIVACY-FOLLOWUP.md)
