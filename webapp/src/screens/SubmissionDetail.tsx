import { Spinner } from "@maxhub/max-ui";
import { useState } from "react";

import { api } from "../api";
import type { BBox, SubmissionDetail } from "../api/types";
import { relativeDate } from "../format";
import { useLoader } from "../hooks";
import { goBack } from "../router";
import { describeSubmission } from "../status";
import { Chip, ErrorState, Screen, ScreenHeader, Skeleton } from "../ui/common";
import { SparkIcon } from "../ui/icons";

function percent(value: number): string {
  return `${Math.min(100, Math.max(0, value * 100)).toFixed(2)}%`;
}

function Photo({ url, bbox }: { url: string; bbox: BBox | null }) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  if (state === "error") {
    return <div className="photo photo-missing">Фото сейчас недоступно</div>;
  }
  return (
    <figure className="photo">
      {state === "loading" && (
        <div className="photo-placeholder">
          <Skeleton height={200} radius={16} />
        </div>
      )}
      <div className="photo-frame" hidden={state !== "ready"}>
        <img
          src={url}
          alt="Фото решения"
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
            aria-label="Строка с ошибкой"
            style={{
              left: percent(bbox.x),
              top: percent(bbox.y),
              width: percent(bbox.width),
              height: percent(bbox.height),
            }}
          />
        )}
      </div>
    </figure>
  );
}

function StatusBanner({ item }: { item: SubmissionDetail }) {
  switch (item.status) {
    case "queued":
    case "processing":
      return (
        <div className="banner banner-accent" role="status">
          <Spinner size={20} appearance="themed" />
          <span>Проверяю решение. Обычно это занимает меньше минуты — я пришлю ответ в чат.</span>
        </div>
      );
    case "needs_confirmation":
      return (
        <div className="banner banner-improving" role="status">
          Я не уверен, что правильно прочитал почерк. Открой чат с ботом и подтверди, что
          распознал верно.
        </div>
      );
    case "failed":
      return (
        <div className="banner banner-neutral" role="status">
          Не получилось разобрать это фото. Попробуй переснять при хорошем свете, чтобы решение
          было целиком в кадре, и отправь боту ещё раз.
        </div>
      );
    case "done":
      return null;
  }
}

function Result({ item }: { item: SubmissionDetail }) {
  const errorPosition = item.lines.findIndex((line) => line.is_error);
  const hasError = item.first_error_step !== null || item.error_type !== null;
  return (
    <>
      {item.status === "done" && !hasError && (
        <div className="banner banner-solid" role="status">
          Ошибок не нашёл — всё решено верно. Так держать!
        </div>
      )}
      {item.lines.length > 0 && (
        <section className="card" aria-label="Распознанное решение">
          <h2 className="card-title">Твоё решение</h2>
          {item.task && <p className="task">{item.task}</p>}
          <ol className="lines">
            {item.lines.map((line, position) => (
              <li
                key={`${line.index}-${position}`}
                className={line.is_error ? "line line-error" : "line"}
                aria-current={line.is_error ? "step" : undefined}
              >
                <span className="line-number">{position + 1}</span>
                <span className="line-math">{line.display || line.latex}</span>
                {line.is_error && <span className="line-flag">ошибка здесь</span>}
                {!line.is_error && line.confidence < 0.6 && (
                  <span className="line-unsure" title="Плохо читается">
                    ?
                  </span>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
      {item.analysis && hasError && (
        <section className="card hint-card" aria-label="Подсказка">
          <div className="hint-head">
            <SparkIcon size={18} />
            <h2 className="card-title">
              {errorPosition >= 0 ? `Ошибка в шаге ${errorPosition + 1}` : "Где ошибка"}
            </h2>
            {item.error_title && <Chip tone="weak">{item.error_title}</Chip>}
          </div>
          {item.analysis.hint && <p className="hint-text">{item.analysis.hint}</p>}
          <p className="hint-note">Ответ не подсказываю — попробуй исправить сам, у тебя получится.</p>
        </section>
      )}
    </>
  );
}

export function SubmissionDetailScreen({ id }: { id: number }) {
  const detail = useLoader(`submission-${id}`, () => api.submission(id));
  const back = () => {
    goBack({ name: "submission", id });
  };

  if (detail.state === "loading") {
    return (
      <Screen label="Разбор">
        <ScreenHeader title="Разбор" onBack={back} />
        <div className="stack" aria-busy="true">
          <Skeleton height={220} radius={20} />
          <Skeleton height={120} radius={20} />
        </div>
      </Screen>
    );
  }
  if (detail.state === "error") {
    return (
      <Screen label="Разбор">
        <ScreenHeader title="Разбор" onBack={back} />
        <ErrorState error={detail.error} onRetry={detail.reload} />
      </Screen>
    );
  }
  const item = detail.data;
  const status = describeSubmission(item);
  return (
    <Screen label="Разбор">
      <ScreenHeader
        title={item.topic_title ?? "Разбор"}
        subtitle={
          <>
            {relativeDate(item.created_at)} · <Chip tone={status.tone}>{status.label}</Chip>
          </>
        }
        onBack={back}
      />
      <div className="stack">
        <StatusBanner item={item} />
        {item.image_url && <Photo url={item.image_url} bbox={item.error_bbox} />}
        <Result item={item} />
      </div>
    </Screen>
  );
}
