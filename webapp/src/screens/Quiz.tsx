import { Spinner } from "@maxhub/max-ui";
import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api";
import type { AnswerResult, Quiz, QuizItem } from "../api/types";
import { countLabel } from "../format";
import { useLoader } from "../hooks";
import { goBack, navigate } from "../router";
import {
  Action,
  Chip,
  EmptyState,
  ErrorState,
  Screen,
  ScreenHeader,
  Skeleton,
} from "../ui/common";
import { CheckIcon, CrossIcon, SparkIcon } from "../ui/icons";

const LETTERS = ["А", "Б", "В", "Г", "Д", "Е"];
function resultFromItem(item: QuizItem, quiz: Quiz): AnswerResult | null {
  if (item.answered_index === null || item.correct_index === null) return null;
  return {
    item_id: item.id,
    chosen_index: item.answered_index,
    correct_index: item.correct_index,
    is_correct: item.answered_index === item.correct_index,
    explanation: null,
    already_answered: true,
    quiz_status: quiz.status,
    answered: quiz.answered,
    total: quiz.total,
    correct: quiz.correct,
  };
}
const toMap = () => {
  navigate({ name: "map" }, { replace: true });
};

function ClosedQuiz({ empty = false }: { empty?: boolean }) {
  return (
    <EmptyState
      icon={<SparkIcon size={28} />}
      title={empty ? "В тесте пока нет вопросов" : "Срок теста истёк"}
      action={
        <Action size="large" stretched onClick={toMap}>
          Вернуться к карте
        </Action>
      }
    >
      <p>
        {empty
          ? "Вернись к карте, чтобы посмотреть доступные темы и тренировки."
          : "Ответить на оставшиеся вопросы уже нельзя. Доступные тренировки можно посмотреть в карте."}
      </p>
    </EmptyState>
  );
}
function Results({ quiz }: { quiz: Quiz }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);
  const repeat = [
    ...new Set(
      quiz.items
        .filter((item) => item.is_correct === false)
        .map((item) => item.topic_title),
    ),
  ];
  return (
    <section className="result" aria-label="Результат теста">
      <div className="result-score">
        <CheckIcon size={28} />
        <strong>
          {quiz.correct} из {quiz.total}
        </strong>
        <span>верных ответов</span>
      </div>
      <h2 ref={heading} tabIndex={-1} className="result-title">
        Тест завершён
      </h2>
      <p className="result-text">
        {quiz.correct === quiz.total
          ? quiz.total === 1
            ? "Ответ верный."
            : `Все ${countLabel(quiz.total, "ответ", "ответа", "ответов")} верные.`
          : "Посмотри темы, к которым стоит вернуться."}
      </p>
      {repeat.length > 0 && (
        <div className="card result-repeat">
          <h3 className="card-title">Стоит повторить</h3>
          <ul>
            {repeat.map((title) => (
              <li key={title}>{title}</li>
            ))}
          </ul>
        </div>
      )}
      <Action size="large" stretched onClick={toMap}>
        Вернуться к карте
      </Action>
    </section>
  );
}

function QuizRunner({ initial }: { initial: Quiz }) {
  const [quiz, setQuiz] = useState(initial);
  const firstOpen = initial.items.findIndex(
    (item) => item.answered_index === null,
  );
  const [position, setPosition] = useState(
    firstOpen === -1 ? initial.items.length : firstOpen,
  );
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [pending, setPending] = useState<number | null>(null);
  const [failure, setFailure] = useState<{
    error: unknown;
    choice: number;
  } | null>(null);
  const lock = useRef(false);
  const question = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    question.current?.focus({ preventScroll: true });
  }, [position]);
  const item = quiz.items[position];
  if (quiz.status === "expired") return <ClosedQuiz />;
  if (!item) return <Results quiz={quiz} />;
  const shown = result ?? resultFromItem(item, quiz);
  const total = quiz.total;

  const accept = (answer: AnswerResult) => {
    setResult(answer);
    setQuiz((current) => ({
      ...current,
      answered: answer.answered,
      correct: answer.correct,
      status: answer.quiz_status,
      items: current.items.map((candidate) =>
        candidate.id === answer.item_id
          ? {
              ...candidate,
              answered_index: answer.chosen_index,
              correct_index: answer.correct_index,
              is_correct: answer.is_correct,
            }
          : candidate,
      ),
    }));
  };
  const choose = async (index: number, recover = false) => {
    if (shown || lock.current) return;
    lock.current = true;
    setPending(index);
    setFailure(null);
    try {
      if (recover) {
        const current = await api.quiz(quiz.id);
        setQuiz(current);
        const saved = current.items.find(
          (candidate) => candidate.id === item.id,
        );
        const savedResult = saved ? resultFromItem(saved, current) : null;
        if (savedResult) {
          accept(savedResult);
          return;
        }
        if (current.status !== "active") return;
      }
      accept(await api.answer(quiz.id, item.id, index));
    } catch (error) {
      setFailure({ error, choice: index });
    } finally {
      lock.current = false;
      setPending(null);
    }
  };
  return (
    <div className="quiz">
      <div className="quiz-progress">
        <span className="quiz-counter">
          Вопрос {position + 1} из {total}
        </span>
        <div
          className="quiz-bar"
          role="progressbar"
          aria-label="Ответы подтверждены"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={quiz.answered}
        >
          <span style={{ width: `${(quiz.answered / total) * 100}%` }} />
        </div>
      </div>
      <div className="quiz-meta">
        <span className="quiz-topic">{item.topic_title}</span>
        {item.from_gap_map && <Chip tone="accent">Из твоей карты</Chip>}
      </div>
      <h2 ref={question} tabIndex={-1} className="quiz-prompt math-text">
        {item.prompt}
      </h2>
      <div
        className="choices"
        role="group"
        aria-label="Варианты ответа"
        aria-busy={pending !== null}
      >
        {item.choices.map((choice) => {
          const correct = shown?.correct_index === choice.index;
          const chosen = shown?.chosen_index === choice.index;
          return (
            <button
              key={choice.index}
              type="button"
              className={`choice ${correct ? "choice-correct" : chosen ? "choice-wrong" : pending === choice.index ? "choice-pending" : ""}`}
              disabled={shown !== null || pending !== null || failure !== null}
              aria-pressed={shown ? chosen : undefined}
              onClick={() => {
                void choose(choice.index);
              }}
            >
              <span className="choice-letter">
                {LETTERS[choice.index] ?? choice.index + 1}
              </span>
              <span className="choice-body">
                <span className="choice-text">{choice.text}</span>
                {shown && (correct || chosen) && (
                  <span className="choice-caption">
                    {chosen ? "Твой ответ" : ""}
                    {chosen && correct ? " · " : ""}
                    {correct ? "Верный ответ" : ""}
                  </span>
                )}
              </span>
              {pending === choice.index && (
                <Spinner size={20} appearance="themed" />
              )}
              {shown && correct && <CheckIcon size={20} />}
              {shown && chosen && !correct && <CrossIcon size={20} />}
            </button>
          );
        })}
      </div>
      {pending !== null && (
        <p className="operation-note" role="status">
          {failure ? "Проверяем ответ…" : "Ожидаем подтверждения ответа…"}
        </p>
      )}
      {failure && (
        <div className="inline-error" role="alert">
          {failure.error instanceof ApiError &&
          [401, 403, 404].includes(failure.error.status) ? (
            <ErrorState
              error={failure.error}
              title={
                failure.error.status === 404 ? "Тест недоступен" : undefined
              }
            />
          ) : (
            <>
              <p>
                Подтверждение ответа не получено. Он мог сохраниться. Проверь
                подключение: приложение сверит ответ с сервером перед повтором.
              </p>
              <Action
                variant="secondary"
                size="large"
                stretched
                onClick={() => {
                  void choose(failure.choice, true);
                }}
              >
                Проверить и повторить
              </Action>
            </>
          )}
        </div>
      )}
      {shown && (
        <>
          <div
            className={`feedback ${shown.is_correct ? "feedback-ok" : "feedback-miss"}`}
            role="status"
          >
            <strong>{shown.is_correct ? "Верно" : "Ответ не совпал"}</strong>
            {shown.already_answered && (
              <span>Показан ранее сохранённый ответ.</span>
            )}
            {!shown.is_correct && (
              <span>
                Верный ответ:{" "}
                {
                  item.choices.find(
                    (choice) => choice.index === shown.correct_index,
                  )?.text
                }
              </span>
            )}
            {shown.explanation && <span>{shown.explanation}</span>}
          </div>
          <Action
            size="large"
            stretched
            onClick={() => {
              setResult(null);
              setPosition((current) => current + 1);
              window.scrollTo(0, 0);
            }}
          >
            {position + 1 < total ? "Следующий вопрос" : "Посмотреть результат"}
          </Action>
        </>
      )}
      <p className="footnote">
        Можно выйти и продолжить позже. Подтверждённые ответы останутся в тесте.
      </p>
    </div>
  );
}
export function QuizScreen({ id }: { id: number }) {
  const quiz = useLoader(`quiz-${id}`, () => api.quiz(id));
  return (
    <Screen label="Тест">
      <ScreenHeader
        title="Тест"
        onBack={() => {
          goBack({ name: "quiz", id });
        }}
      />
      {quiz.state === "loading" && (
        <div className="stack" aria-busy="true" aria-label="Загрузка теста">
          <Skeleton height={8} />
          <Skeleton height={64} />
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} height={64} />
          ))}
        </div>
      )}
      {quiz.state === "error" && (
        <ErrorState
          error={quiz.error}
          onRetry={quiz.reload}
          title={
            quiz.error instanceof ApiError && quiz.error.kind === "not_found"
              ? "Тест недоступен"
              : undefined
          }
        />
      )}
      {quiz.data &&
        (quiz.data.status === "expired" ? (
          <ClosedQuiz />
        ) : !quiz.data.items.length ? (
          <ClosedQuiz empty />
        ) : (
          <QuizRunner initial={quiz.data} />
        ))}
    </Screen>
  );
}
