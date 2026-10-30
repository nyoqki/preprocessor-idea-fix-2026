import { Button } from "@maxhub/max-ui";
import { useState } from "react";

import { api } from "../api";
import type { AnswerResult, Quiz, QuizItem } from "../api/types";
import { countLabel, describeError } from "../format";
import { useLoader } from "../hooks";
import { haptics } from "../max";
import { goBack, navigate } from "../router";
import { Chip, EmptyState, ErrorState, Screen, ScreenHeader, Skeleton } from "../ui/common";
import { CheckIcon, CrossIcon, SparkIcon } from "../ui/icons";

const LETTERS = ["А", "Б", "В", "Г", "Д", "Е"];

function resultFromItem(item: QuizItem): AnswerResult | null {
  if (item.answered_index === null || item.correct_index === null) return null;
  return {
    item_id: item.id,
    chosen_index: item.answered_index,
    correct_index: item.correct_index,
    is_correct: item.answered_index === item.correct_index,
    explanation: null,
    already_answered: true,
    quiz_status: "active",
    answered: 0,
    total: 0,
    correct: 0,
  };
}

function choiceClass(index: number, result: AnswerResult | null, pending: number | null): string {
  if (result) {
    if (index === result.correct_index) return "choice choice-correct";
    if (index === result.chosen_index) return "choice choice-wrong";
    return "choice choice-dim";
  }
  return index === pending ? "choice choice-pending" : "choice";
}

function Results({ quiz, onDone }: { quiz: Quiz; onDone: () => void }) {
  const correct = quiz.items.filter((item) => item.is_correct).length;
  const total = quiz.items.length;
  const ratio = total > 0 ? correct / total : 0;
  const title = ratio === 1 ? "Идеально!" : ratio >= 0.6 ? "Хороший результат!" : "Есть над чем поработать";
  const text =
    ratio === 1
      ? "Все ответы верные. Темы из карты становятся всё крепче."
      : ratio >= 0.6
        ? "Большую часть ты уже знаешь. Ошибки я добавил в карту — повторим их чуть позже."
        : "Не страшно: ошибки попали в карту пробелов, и я напомню повторить их через пару дней.";
  return (
    <div className="result">
      <div className="result-score" aria-label={`${correct} из ${total}`}>
        <span className="result-number">{correct}</span>
        <span className="result-total">из {total}</span>
      </div>
      <h2 className="result-title">{title}</h2>
      <p className="result-text">{text}</p>
      <ul className="result-list">
        {quiz.items.map((item) => (
          <li key={item.id} className={item.is_correct ? "result-ok" : "result-miss"}>
            {item.is_correct ? <CheckIcon size={18} /> : <CrossIcon size={18} />}
            <span>{item.topic_title}</span>
          </li>
        ))}
      </ul>
      <Button size="large" variant="primary" stretched onClick={onDone}>
        Вернуться к карте
      </Button>
    </div>
  );
}

function QuizRunner({ initial }: { initial: Quiz }) {
  const [quiz, setQuiz] = useState(initial);
  const firstOpen = initial.items.findIndex((item) => item.answered_index === null);
  const [position, setPosition] = useState(firstOpen === -1 ? initial.items.length : firstOpen);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [pending, setPending] = useState<number | null>(null);
  const [failure, setFailure] = useState<unknown>(null);

  const item = quiz.items[position];
  const toMap = () => {
    navigate({ name: "map" }, { replace: true });
  };

  if (!item) {
    return <Results quiz={quiz} onDone={toMap} />;
  }

  const shown = result ?? resultFromItem(item);
  const total = quiz.items.length;

  const choose = (index: number) => {
    if (shown || pending !== null) return;
    haptics.selection();
    setPending(index);
    setFailure(null);
    api.answer(quiz.id, item.id, index).then(
      (answer) => {
        haptics.notify(answer.is_correct ? "success" : "error");
        setResult(answer);
        setPending(null);
        setQuiz((current) => ({
          ...current,
          answered: answer.answered,
          correct: answer.correct,
          status: answer.quiz_status,
          items: current.items.map((candidate) =>
            candidate.id === item.id
              ? {
                  ...candidate,
                  answered_index: answer.chosen_index,
                  correct_index: answer.correct_index,
                  is_correct: answer.is_correct,
                }
              : candidate,
          ),
        }));
      },
      (error: unknown) => {
        haptics.notify("warning");
        setPending(null);
        setFailure(error);
      },
    );
  };

  const next = () => {
    haptics.impact("light");
    setResult(null);
    setPosition((current) => current + 1);
  };

  return (
    <div className="quiz">
      <div className="quiz-progress">
        <span className="quiz-counter" aria-live="polite">
          {position + 1} / {total}
        </span>
        <div
          className="quiz-bar"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={position + (shown ? 1 : 0)}
        >
          <span style={{ width: `${((position + (shown ? 1 : 0)) / total) * 100}%` }} />
        </div>
      </div>
      <div className="quiz-meta">
        {item.from_gap_map && (
          <Chip tone="accent">
            <SparkIcon size={14} /> вопрос из твоей карты
          </Chip>
        )}
        <span className="quiz-topic">{item.topic_title}</span>
      </div>
      <h2 className="quiz-prompt">{item.prompt}</h2>
      <div className="choices" role="group" aria-label="Варианты ответа">
        {item.choices.map((choice) => (
          <button
            key={choice.index}
            type="button"
            className={choiceClass(choice.index, shown, pending)}
            disabled={shown !== null || pending !== null}
            aria-pressed={shown ? choice.index === shown.chosen_index : undefined}
            onClick={() => {
              choose(choice.index);
            }}
          >
            <span className="choice-letter">{LETTERS[choice.index] ?? choice.index + 1}</span>
            <span className="choice-text">{choice.text}</span>
            {shown && choice.index === shown.correct_index && <CheckIcon size={20} />}
            {shown && choice.index === shown.chosen_index && !shown.is_correct && (
              <CrossIcon size={20} />
            )}
          </button>
        ))}
      </div>
      {failure !== null && (
        <div className="banner banner-neutral" role="alert">
          {describeError(failure).title}. Нажми на ответ ещё раз.
        </div>
      )}
      {shown && (
        <div className={shown.is_correct ? "feedback feedback-ok" : "feedback feedback-miss"} role="status">
          <strong>{shown.is_correct ? "Верно!" : "Не совсем"}</strong>
          {!shown.is_correct && (
            <span>{shown.explanation ?? "Правильный ответ отмечен зелёным. Запомни его — мы ещё вернёмся к этой теме."}</span>
          )}
        </div>
      )}
      {shown && (
        <div className="quiz-actions">
          <Button size="large" variant="primary" stretched onClick={next}>
            {position + 1 < total ? "Дальше" : "Посмотреть результат"}
          </Button>
        </div>
      )}
    </div>
  );
}

export function QuizScreen({ id }: { id: number }) {
  const quiz = useLoader(`quiz-${id}`, () => api.quiz(id));
  const back = () => {
    goBack({ name: "quiz", id });
  };
  const title = quiz.data ? `Тест · ${countLabel(quiz.data.items.length, "вопрос", "вопроса", "вопросов")}` : "Тест";

  return (
    <Screen label="Тест">
      <ScreenHeader title={title} onBack={back} />
      {quiz.state === "loading" && (
        <div className="stack" aria-busy="true">
          <Skeleton height={8} />
          <Skeleton height={60} radius={16} />
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} height={56} radius={16} />
          ))}
        </div>
      )}
      {quiz.state === "error" && <ErrorState error={quiz.error} onRetry={quiz.reload} />}
      {quiz.state === "ready" &&
        (quiz.data.status === "expired" ? (
          <EmptyState icon={<SparkIcon size={32} />} title="Этот тест уже закрыт">
            <p>Не переживай — я соберу новый, когда придёт время повторить темы из карты.</p>
          </EmptyState>
        ) : quiz.data.items.length === 0 ? (
          <EmptyState icon={<SparkIcon size={32} />} title="В тесте пока нет вопросов">
            <p>Загляни чуть позже.</p>
          </EmptyState>
        ) : (
          <QuizRunner initial={quiz.data} />
        ))}
    </Screen>
  );
}
