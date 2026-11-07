import { CellList, CellSimple, Input } from "@maxhub/max-ui";
import { useState } from "react";
import {
  Action,
  Chip,
  EmptyState,
  ErrorState,
  Screen,
  ScreenHeader,
  SkeletonCards,
} from "../ui/common";
import { ApiError } from "../api";
import { CameraIcon, CheckIcon, SearchIcon } from "../ui/icons";
import { Photo } from "../screens/SubmissionDetail";
import { TeacherTopicRow } from "../screens/Teacher";

const scenarios = [
  "default",
  "loading",
  "error",
  "empty",
  "no-test",
  "quiz-error",
  "no-class",
  "auth",
  "forbidden",
  "not-found",
  "pagination-error",
  "correct",
  "review",
  "incomplete",
  "unknown",
  "queued",
  "processing",
  "confirmation",
  "failed",
  "photo-error",
  "answer-error",
  "answer-saved",
  "expired",
  "completed",
  "long",
];
export default function Catalog() {
  const params = new URLSearchParams(location.search);
  const [scheme, setScheme] = useState(params.get("theme") ?? "system");
  const [scenario, setScenario] = useState("default");
  const [role, setRole] = useState("student");
  const [text, setText] = useState("");
  const [clicks, setClicks] = useState(0);
  const link = (hash: string) =>
    `?${new URLSearchParams({ theme: scheme, scenario, role })}#${hash}`;
  return (
    <div className="shell shell-focus">
      <Screen label="Каталог Ясно">
        <ScreenHeader
          title="Ясно · каталог"
          subtitle="Служебная проверка компонентов и состояний. Доступен только в dev."
        />
        <div className="catalog-controls">
          <label>
            Тема
            <select
              aria-label="Тема"
              value={scheme}
              onChange={(event) => {
                const value = event.target.value;
                setScheme(value);
                const url = new URL(location.href);
                url.searchParams.set("theme", value);
                history.replaceState(null, "", url);
                window.dispatchEvent(new Event("yasno-theme"));
              }}
            >
              <option value="system">Системная</option>
              <option value="light">Светлая</option>
              <option value="dark">Тёмная</option>
            </select>
          </label>
          <label>
            Роль в демо
            <select
              aria-label="Роль в демо"
              value={role}
              onChange={(e) => {
                setRole(e.target.value);
              }}
            >
              <option value="student">Ученик</option>
              <option value="teacher">Учитель</option>
            </select>
          </label>
          <label>
            Сценарий
            <select
              aria-label="Сценарий"
              value={scenario}
              onChange={(e) => {
                setScenario(e.target.value);
              }}
            >
              {scenarios.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>
        <Action
          variant="secondary"
          onClick={() => {
            for (const key of Object.keys(sessionStorage))
              if (key.startsWith("yasno-demo-quiz:")) sessionStorage.removeItem(key);
            setClicks(0);
          }}
        >
          Сбросить ответы демо
        </Action>
        <nav className="catalog-nav" aria-label="Экраны демо">
          {(
            [
              ["/map", "Карта"],
              ["/submissions", "Разборы"],
              ["/submissions/41", "Разбор"],
              ["/quiz/7", "Тест"],
              ["/class", "Класс"],
              ["/teacher", "Учитель"],
            ] as const
          ).map(([path, title]) => (
            <a href={link(path)} key={path}>
              {title}
            </a>
          ))}
        </nav>
        <section className="catalog-section">
          <h2 className="section-title">Действия</h2>
          <Action
            size="large"
            stretched
            iconBefore={<CheckIcon size={20} />}
            onClick={() => {
              setClicks((n) => n + 1);
            }}
          >
            Основная кнопка
          </Action>
          <Action size="large" stretched loading>
            Отправка ответа
          </Action>
          <Action size="large" stretched disabled>
            Недоступное действие
          </Action>
          <Action
            size="large"
            variant="secondary"
            stretched
            onClick={() => {
              setClicks((n) => n + 1);
            }}
          >
            Вторичная кнопка
          </Action>
          <Action size="large" variant="secondary" stretched loading>
            Загрузка
          </Action>
          <Action
            variant="ghost"
            onClick={() => {
              setClicks((n) => n + 1);
            }}
          >
            Дополнительное действие
          </Action>
          <p className="footnote" role="status">
            Нажатий: {clicks}
          </p>
        </section>
        <section className="catalog-section">
          <h2 className="section-title">Поиск и списки</h2>
          <Input
            aria-label="Поиск в каталоге"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
            withClearButton
            placeholder="Найти в материалах"
            iconBefore={<SearchIcon size={20} />}
            innerClassNames={{
              container: "search-field",
              input: "search-input",
              clearButton: "search-clear",
            }}
          />
          <CellList mode="island" filled>
            <CellSimple
              as="button"
              title="Квадратные уравнения и выражения с параметром"
              subtitle="Нужно пояснить шаг · сегодня, 18:30"
              showChevron
              onClick={() => {
                setClicks((n) => n + 1);
              }}
              innerClassNames={{
                title: "history-title",
                subtitle: "history-subtitle",
              }}
            />
          </CellList>
          <div className="catalog-controls">
            <Chip tone="weak">Стоит повторить</Chip>
            <Chip tone="improving">Закрепляем</Chip>
            <Chip tone="solid">Освоено</Chip>
            <Chip tone="neutral">Нет данных</Chip>
          </div>
        </section>
        <section className="catalog-section">
          <h2 className="section-title">Математика и ответ</h2>
          <div className="card">
            <ol className="lines">
              <li className="line line-error">
                <span className="line-number">2</span>
                <span className="line-math" tabIndex={0}>
                  D = (−5)² − 4 · 1 · 6 = 25 + 24 = 49
                </span>
                <span className="line-flag">Проверь шаг</span>
              </li>
            </ol>
          </div>
          <button
            className="choice choice-correct"
            onClick={() => {
              setClicks((n) => n + 1);
            }}
          >
            <span className="choice-letter">Б</span>
            <span className="choice-body">
              <span>1</span>
              <span className="choice-caption">Твой ответ · Верный ответ</span>
            </span>
            <CheckIcon size={20} />
          </button>
          <div className="feedback feedback-miss">
            <strong>Ответ не совпал</strong>
            <span>Верный ответ: 1</span>
          </div>
        </section>
        <section className="catalog-section">
          <h2 className="section-title">Фото и координаты</h2>
          <Photo
            url={`data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="240"><rect width="600" height="240" fill="#fff"/><text x="40" y="80" font-size="32" fill="#060708">x² − 5x + 6 = 0</text><text x="40" y="170" font-size="32" fill="#060708">D = 25 + 24 = 49</text></svg>')}`}
            bbox={{ x: 0.04, y: 0.5, width: 0.85, height: 0.3 }}
            step={2}
          />
        </section>
        <section className="catalog-section">
          <h2 className="section-title">Состояния</h2>
          <SkeletonCards count={1} />
          <EmptyState icon={<CameraIcon size={28} />} title="Карта пока пустая">
            <p>Отправь фото своего решения боту в личный чат.</p>
          </EmptyState>
          <ErrorState
            error={new ApiError("network", 0, "demo")}
            onRetry={() => {
              setClicks((n) => n + 1);
            }}
          />
        </section>
        <section className="catalog-section">
          <h2 className="section-title">Сводка класса</h2>
          <TeacherTopicRow
            students={27}
            topic={{
              code: "demo",
              title: "Квадратные уравнения",
              weak: 9,
              improving: 4,
              solid: 2,
              top_error_type: {
                code: "sign",
                title: "Ошибка в знаке",
                count: 12,
              },
            }}
          />
        </section>
      </Screen>
    </div>
  );
}
