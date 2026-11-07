import { Spinner } from "@maxhub/max-ui";
import { useState } from "react";

import { api, ApiError } from "../api";
import type { BBox, SubmissionDetail } from "../api/types";
import { relativeDate } from "../format";
import { useLoader } from "../hooks";
import { goBack } from "../router";
import { describeSubmission } from "../status";
import {
  Action,
  ChatAction,
  ErrorState,
  InlineError,
  Screen,
  ScreenHeader,
  Skeleton,
  Chip,
} from "../ui/common";
import { SparkIcon } from "../ui/icons";

const percent = (value: number) => `${Math.min(100, Math.max(0, value * 100))}%`;

export function Photo({
  url,
  bbox,
  step,
}: {
  url: string;
  bbox: BBox | null;
  step: number | null;
}) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [attempt, setAttempt] = useState(0);
  if (state === "error")
    return (
      <div className="photo-missing">
        <p>Фото недоступно. Текст разбора остаётся ниже.</p>
        <Action
          variant="secondary"
          size="medium"
          onClick={() => {
            setAttempt((n) => n + 1);
            setState("loading");
          }}
        >
          Загрузить фото
        </Action>
      </div>
    );
  return (
    <figure className="photo" aria-label="Фото решения">
      {state === "loading" && (
        <div aria-busy="true" aria-label="Загрузка фото">
          <Skeleton height={200} radius={16} />
        </div>
      )}
      <div className="photo-frame" hidden={state !== "ready"}>
        <img
          key={attempt}
          src={url}
          alt="Фото твоего решения из тетради"
          onLoad={() => {
            setState("ready");
          }}
          onError={() => {
            setState("error");
          }}
        />
        {bbox && (
          <span
            className="photo-mark"
            role="img"
            aria-label={step ? `Проверь шаг ${step}` : "Строка с ошибкой"}
            style={{
              left: percent(bbox.x),
              top: percent(bbox.y),
              width: percent(Math.min(bbox.width, 1 - bbox.x)),
              height: percent(Math.min(bbox.height, 1 - bbox.y)),
            }}
          >
            {step && <span className="photo-label">Шаг {step}</span>}
          </span>
        )}
      </div>
      {bbox && step && (
        <figcaption>Рамкой выделен шаг {step}. Он отмечен и в списке ниже.</figcaption>
      )}
    </figure>
  );
}

function ResultBanner({ item }: { item: SubmissionDetail }) {
  const status = describeSubmission(item);
  const text =
    item.status === "queued"
      ? "Фото ожидает обработки. Обнови состояние, чтобы проверить результат."
      : item.status === "processing"
        ? "Результат появится после обработки. Его также можно посмотреть в чате."
        : item.status === "needs_confirmation"
          ? "В чате можно проверить распознанные строки и уточнить запись."
          : item.status === "failed"
            ? "Причину не удалось определить. Вернись в чат и попробуй отправить фото ещё раз."
            : item.verdict === "correct"
              ? "В проверенных шагах ошибок не найдено."
              : item.verdict === "error"
                ? "Начни с отмеченного шага. Подсказка поможет проверить преобразование."
                : item.verdict === "incomplete"
                  ? "Продолжи решение в тетради. Вопрос по следующему шагу можно задать в чате."
                  : item.verdict === "review"
                    ? "Этот переход не удалось проверить однозначно. Поясни его в чате."
                    : "Обнови разбор или вернись в чат, чтобы уточнить результат.";
  return (
    <section
      className={`result-banner banner-${status.tone}`}
      aria-label="Результат разбора"
      role="status"
    >
      <div className="result-banner-head">
        {["queued", "processing"].includes(item.status) && (
          <Spinner size={20} appearance="themed" />
        )}
        <h2>{status.label}</h2>
      </div>
      <p>{text}</p>
    </section>
  );
}

export function SubmissionDetailScreen({ id }: { id: number }) {
  const detail = useLoader(`submission-${id}`, () => api.submission(id));
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<unknown>(null);
  const back = () => {
    goBack({ name: "submission", id });
  };
  const refresh = () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshError(null);
    api
      .submission(id)
      .then(detail.setData, setRefreshError)
      .finally(() => {
        setRefreshing(false);
      });
  };
  if (!detail.data)
    return (
      <Screen label="Разбор">
        <ScreenHeader title="Разбор" onBack={back} />
        {detail.state === "error" ? (
          <ErrorState
            error={detail.error}
            onRetry={detail.reload}
            title={
              detail.error instanceof ApiError && detail.error.kind === "not_found"
                ? "Разбор недоступен"
                : undefined
            }
          />
        ) : (
          <div className="stack" aria-busy="true" aria-label="Загрузка разбора">
            <Skeleton height={100} />
            <Skeleton height={220} />
          </div>
        )}
      </Screen>
    );
  const item = detail.data;

  const errorLine = item.lines.find((line) => line.index === item.first_error_step);
  const step = item.first_error_step === null ? null : item.first_error_step + 1;
  const isError = item.status === "done" && item.verdict === "error";
  return (
    <Screen label="Разбор">
      <ScreenHeader
        title={item.topic_title ?? "Разбор решения"}
        subtitle={relativeDate(item.created_at)}
        onBack={back}
      />
      <ResultBanner item={item} />
      {refreshError !== null && (
        <InlineError onRetry={refresh} loading={refreshing}>
          Не удалось обновить разбор. Предыдущий результат остаётся на экране.
        </InlineError>
      )}
      {(["queued", "processing"].includes(item.status) ||
        (item.status === "done" &&
          !["correct", "error", "incomplete", "review"].includes(item.verdict ?? ""))) &&
        refreshError === null && (
          <Action variant="secondary" size="medium" loading={refreshing} onClick={refresh}>
            Обновить состояние
          </Action>
        )}
      {item.image_url ? (
        <Photo
          key={item.image_url}
          url={item.image_url}
          bbox={isError ? (errorLine?.bbox ?? item.error_bbox) : null}
          step={step}
        />
      ) : (
        <p className="photo-missing">Фото недоступно</p>
      )}
      {item.lines.length > 0 && (
        <section className="card" aria-labelledby="solution-title">
          <h2 className="card-title" id="solution-title">
            Твоё решение
          </h2>
          {item.task && <p className="task math-text">{item.task}</p>}
          <ol className="lines">
            {item.lines.map((line) => {
              const marked = isError && line.index === item.first_error_step;
              return (
                <li key={line.index} className={marked ? "line line-error" : "line"}>
                  <span className="line-number">{line.index + 1}</span>
                  <span
                    className="line-math"
                    tabIndex={0}
                    aria-label={`Шаг ${line.index + 1}: ${line.display || line.latex}`}
                  >
                    {line.display || line.latex}
                  </span>
                  {marked && <span className="line-flag">Проверь шаг</span>}
                  {line.confidence < 0.6 && (
                    <span className="line-uncertain">Запись нужно уточнить</span>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}
      {item.analysis?.hint && item.status === "done" && item.verdict !== "correct" && (
        <section className="card hint-card" aria-label="Подсказка">
          <div className="hint-head">
            <SparkIcon size={20} />
            <h2 className="card-title">
              {isError && step ? `Подсказка к шагу ${step}` : "Подсказка"}
            </h2>
          </div>
          {isError && item.error_title && <Chip tone="weak">{item.error_title}</Chip>}
          <p className="hint-text">{item.analysis.hint}</p>
        </section>
      )}
      {item.verdict !== "correct" && <ChatAction />}
    </Screen>
  );
}
