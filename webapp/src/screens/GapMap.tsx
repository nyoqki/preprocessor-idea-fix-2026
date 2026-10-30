import { Button } from "@maxhub/max-ui";

import { api } from "../api";
import type { GapStatus, Me, QuizSummary, TopicGap } from "../api/types";
import { countLabel, untilDate } from "../format";
import { useLoader } from "../hooks";
import { haptics } from "../max";
import { navigate } from "../router";
import { Chip, EmptyState, ErrorState, Screen, ScreenHeader, SkeletonCards } from "../ui/common";
import { CameraIcon, SparkIcon } from "../ui/icons";

const STATUS_LABEL: Record<GapStatus, string> = {
  weak: "Нужно подтянуть",
  improving: "Уже лучше",
  solid: "Освоено",
};

function minutesFor(total: number): number {
  return Math.max(1, Math.round(total * 0.6));
}

function QuizCta({ quiz }: { quiz: QuizSummary }) {
  const topic = quiz.topic_titles[0] ?? "твои темы";
  const started = quiz.answered > 0;
  const remaining = quiz.total - quiz.answered;
  return (
    <section className="cta-card" aria-label="Тест по твоей карте">
      <div className="cta-badge">
        <SparkIcon size={16} />
        <span>{quiz.reason === "exam" ? "Перед контрольной" : "Пора повторить"}</span>
      </div>
      <h2 className="cta-title">Повторим «{topic}»?</h2>
      <p className="cta-text">
        {countLabel(started ? remaining : quiz.total, "вопрос", "вопроса", "вопросов")},{" "}
        {countLabel(minutesFor(started ? remaining : quiz.total), "минута", "минуты", "минут")}
        {quiz.topic_titles.length > 1 && ` · ещё ${quiz.topic_titles.slice(1).join(", ")}`}
      </p>
      <Button
        size="large"
        variant="primary-contrast"
        stretched
        onClick={() => {
          haptics.impact("medium");
          navigate({ name: "quiz", id: quiz.id });
        }}
      >
        {started ? "Продолжить тест" : "Начать тест"}
      </Button>
    </section>
  );
}

function TopicCard({ topic }: { topic: TopicGap }) {
  const review = topic.status === "solid" ? null : untilDate(topic.next_review_at);
  const mistakes =
    topic.status === "solid" ? "чисто" : countLabel(topic.mistakes_total, "ошибка", "ошибки", "ошибок");
  return (
    <article className={`topic-card topic-${topic.status}`}>
      <span className="topic-bar" aria-hidden="true" />
      <div className="topic-body">
        <div className="topic-head">
          <h3 className="topic-title">{topic.title}</h3>
          <Chip tone={topic.status}>{mistakes}</Chip>
        </div>
        <p className="topic-status">
          {STATUS_LABEL[topic.status]}
          {review && <span className="topic-review"> · {review}</span>}
        </p>
        {topic.status !== "solid" && topic.error_types.length > 0 && (
          <ul className="topic-errors">
            {topic.error_types.slice(0, 2).map((error) => (
              <li key={error.code}>
                {error.title}
                {error.count > 1 && <span className="topic-errors-count"> ×{error.count}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}

function headline(weak: number, improving: number): string {
  if (weak > 0) return `${countLabel(weak, "тема требует", "темы требуют", "тем требуют")} внимания`;
  if (improving > 0) return "Ты на верном пути — продолжай";
  return "Всё чисто — так держать!";
}

export function GapMapScreen({ me }: { me: Me | null }) {
  const gaps = useLoader("gaps", () => api.gaps());
  const active = useLoader("active-quiz", () => api.activeQuiz());
  const greeting = me?.first_name ? `Привет, ${me.first_name}!` : "Привет!";

  if (gaps.state === "error") {
    return (
      <Screen label="Карта пробелов">
        <ScreenHeader title="Карта пробелов" />
        <ErrorState
          error={gaps.error}
          onRetry={() => {
            gaps.reload();
            active.reload();
          }}
        />
      </Screen>
    );
  }

  const data = gaps.data;
  const quiz = active.data?.quiz ?? null;

  return (
    <Screen label="Карта пробелов">
      <ScreenHeader
        title="Карта пробелов"
        subtitle={data ? `${greeting} ${headline(data.summary.weak, data.summary.improving)}` : greeting}
      />
      {data === null ? (
        <SkeletonCards count={4} />
      ) : data.topics.length === 0 ? (
        <>
          {quiz && <QuizCta quiz={quiz} />}
          <EmptyState icon={<CameraIcon size={32} />} title="Карта пока пустая">
            <p>
              Сфотографируй решение из тетради и отправь его боту «Ясно» в чат. Я найду шаг с
              ошибкой и объясню, что не так, — а тема появится здесь.
            </p>
          </EmptyState>
        </>
      ) : (
        <div className="stack">
          <div className="summary" role="list" aria-label="Сводка">
            <div className="summary-item summary-weak" role="listitem">
              <strong>{data.summary.weak}</strong>
              <span>подтянуть</span>
            </div>
            <div className="summary-item summary-improving" role="listitem">
              <strong>{data.summary.improving}</strong>
              <span>уже лучше</span>
            </div>
            <div className="summary-item summary-solid" role="listitem">
              <strong>{data.summary.solid}</strong>
              <span>освоено</span>
            </div>
          </div>
          {quiz && <QuizCta quiz={quiz} />}
          <h2 className="section-title">Темы</h2>
          {data.topics.map((topic) => (
            <TopicCard key={topic.code} topic={topic} />
          ))}
        </div>
      )}
    </Screen>
  );
}
