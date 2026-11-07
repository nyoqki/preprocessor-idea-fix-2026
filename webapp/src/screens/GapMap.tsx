import { api } from "../api";
import type { Me, QuizSummary, TopicGap } from "../api/types";
import { countLabel, untilDate } from "../format";
import { useLoader } from "../hooks";
import { navigate } from "../router";
import { TOPIC_LABEL } from "../status";
import {
  Action,
  ChatAction,
  Chip,
  EmptyState,
  ErrorState,
  InlineError,
  Screen,
  ScreenHeader,
  SkeletonCards,
} from "../ui/common";
import { CameraIcon, SparkIcon } from "../ui/icons";

function QuizCta({ quiz }: { quiz: QuizSummary }) {
  const started = quiz.answered > 0;
  return (
    <section className="cta-card" aria-label="Актуальный тест">
      <div className="eyebrow">
        <SparkIcon size={18} />
        {quiz.reason === "exam" ? "Перед контрольной" : "Тренировка по твоим темам"}
      </div>
      <h2 className="cta-title">{started ? "Продолжим тренировку" : "Короткий тест"}</h2>
      <p className="cta-text">{quiz.topic_titles.join(" · ") || "Темы из твоей карты"}</p>
      <p className="cta-detail">
        {countLabel(quiz.total, "вопрос", "вопроса", "вопросов")}
        {started && ` · отвечено ${quiz.answered} из ${quiz.total}`}
      </p>
      <Action
        size="large"
        stretched
        onClick={() => {
          navigate({ name: "quiz", id: quiz.id });
        }}
      >
        {started ? "Продолжить тест" : "Начать тест"}
      </Action>
    </section>
  );
}

function TopicCard({ topic }: { topic: TopicGap }) {
  const review = untilDate(topic.next_review_at);
  return (
    <article className={`topic-card topic-${topic.status}`}>
      <div className="topic-head">
        <h3 className="topic-title">{topic.title}</h3>
      </div>
      <div className="topic-meta">
        <Chip tone={topic.status}>{TOPIC_LABEL[topic.status]}</Chip>
        {review && <span className="muted">{review}</span>}
      </div>
      {topic.status !== "solid" && topic.error_types.length > 0 && (
        <p className="topic-errors">{topic.error_types.map((error) => error.title).join(" · ")}</p>
      )}
      <p className="topic-history">
        За всё время: {countLabel(topic.mistakes_total, "ошибка", "ошибки", "ошибок")} ·{" "}
        {countLabel(topic.correct_total, "верный ответ", "верных ответа", "верных ответов")}
      </p>
    </article>
  );
}

export function GapMapScreen({ me }: { me: Me | null }) {
  const gaps = useLoader("gaps", () => api.gaps());
  const active = useLoader("active-quiz", () => api.activeQuiz());
  const data = gaps.data;
  return (
    <Screen label="Карта тем">
      <ScreenHeader
        title="Карта тем"
        subtitle={me?.grade ? `Математика · ${me.grade} класс` : "Математика · твои темы"}
      />
      {active.state === "loading" && <SkeletonCards count={1} height={180} />}
      {active.state === "error" && (
        <InlineError onRetry={active.reload}>
          Не удалось загрузить актуальный тест. Картой можно пользоваться.
        </InlineError>
      )}
      {active.data?.quiz && <QuizCta quiz={active.data.quiz} />}
      {gaps.state === "loading" && <SkeletonCards count={3} />}
      {gaps.state === "error" && <ErrorState error={gaps.error} onRetry={gaps.reload} />}
      {data &&
        (data.topics.length === 0 ? (
          <EmptyState
            icon={<CameraIcon size={28} />}
            title="Карта пока пустая"
            action={<ChatAction primary />}
          >
            <p>
              Отправь фото своего решения боту в личный чат. После разбора здесь появятся темы для
              повторения.
            </p>
          </EmptyState>
        ) : (
          <>
            <div className="summary" aria-label="Сводка тем">
              {(["weak", "improving", "solid"] as const).map((status) => (
                <div className="summary-item" key={status}>
                  <strong>{data.summary[status]}</strong>
                  <span>{TOPIC_LABEL[status]}</span>
                </div>
              ))}
            </div>
            <section className="stack" aria-labelledby="topics-title">
              <h2 className="section-title" id="topics-title">
                Твои темы
              </h2>
              {data.topics.map((topic) => (
                <TopicCard key={topic.code} topic={topic} />
              ))}
            </section>
            <p className="footnote">Карта отражает темы из твоих разборов и тестов.</p>
          </>
        ))}
    </Screen>
  );
}
