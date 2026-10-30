import { api } from "../api";
import type { TeacherTopic } from "../api/types";
import { countLabel } from "../format";
import { useLoader } from "../hooks";
import { EmptyState, ErrorState, Screen, ScreenHeader, SkeletonCards } from "../ui/common";
import { ChartIcon } from "../ui/icons";

function TopicRow({ topic, scale }: { topic: TeacherTopic; scale: number }) {
  const total = topic.weak + topic.improving + topic.solid;
  const width = (value: number) => `${(value / scale) * 100}%`;
  return (
    <article className="card teacher-topic">
      <div className="teacher-head">
        <h3 className="topic-title">{topic.title}</h3>
        <span className="teacher-count">{countLabel(total, "ученик", "ученика", "учеников")}</span>
      </div>
      <div
        className="stacked-bar"
        role="img"
        aria-label={`Плывут: ${topic.weak}, подтягиваются: ${topic.improving}, освоили: ${topic.solid}`}
      >
        <span className="bar-weak" style={{ width: width(topic.weak) }} />
        <span className="bar-improving" style={{ width: width(topic.improving) }} />
        <span className="bar-solid" style={{ width: width(topic.solid) }} />
      </div>
      <dl className="teacher-legend">
        <div>
          <dt className="dot dot-weak">плывут</dt>
          <dd>{topic.weak}</dd>
        </div>
        <div>
          <dt className="dot dot-improving">подтягиваются</dt>
          <dd>{topic.improving}</dd>
        </div>
        <div>
          <dt className="dot dot-solid">освоили</dt>
          <dd>{topic.solid}</dd>
        </div>
      </dl>
      {topic.top_error_type && (
        <p className="teacher-error">
          Частая ошибка: <strong>{topic.top_error_type.title}</strong>
        </p>
      )}
    </article>
  );
}

export function TeacherScreen() {
  const summary = useLoader("teacher", () => api.teacherSummary());
  const data = summary.data;
  const scale = data
    ? Math.max(1, ...data.topics.map((topic) => topic.weak + topic.improving + topic.solid))
    : 1;

  return (
    <Screen label="Где класс плывёт">
      <ScreenHeader
        title="Где класс плывёт"
        subtitle={
          data?.school_class
            ? `${data.school_class.title}: ${countLabel(data.students_with_gaps, "ученику", "ученикам", "ученикам")} из ${data.students_total} стоит повторить темы`
            : "Сводка без имён — только сколько учеников путается в каждой теме"
        }
      />
      {summary.state === "loading" && <SkeletonCards count={3} height={130} />}
      {summary.state === "error" && <ErrorState error={summary.error} onRetry={summary.reload} />}
      {data &&
        (data.school_class === null ? (
          <EmptyState icon={<ChartIcon size={32} />} title="Класс не привязан">
            <p>Добавь бота «Ясно» в чат класса — и здесь появится сводка по темам.</p>
          </EmptyState>
        ) : data.topics.length === 0 ? (
          <EmptyState icon={<ChartIcon size={32} />} title="Пока всё спокойно">
            <p>Как только ученики начнут присылать решения, здесь будет видно, какие темы стоит разобрать на уроке.</p>
          </EmptyState>
        ) : (
          <div className="stack">
            <p className="privacy-note">Данные обезличены: видно только количество учеников, без имён.</p>
            {data.topics.map((topic) => (
              <TopicRow key={topic.code} topic={topic} scale={scale} />
            ))}
          </div>
        ))}
    </Screen>
  );
}
