import { api } from "../api";
import type { TeacherTopic } from "../api/types";
import { countLabel } from "../format";
import { useLoader } from "../hooks";
import {
  ChatAction,
  EmptyState,
  ErrorState,
  Screen,
  ScreenHeader,
  SkeletonCards,
} from "../ui/common";
import { ChartIcon } from "../ui/icons";

export function TeacherTopicRow({ topic, students }: { topic: TeacherTopic; students: number }) {
  const total = topic.weak + topic.improving + topic.solid;
  const width = (value: number) => `${(value / Math.max(1, students)) * 100}%`;
  return (
    <article className="card teacher-topic">
      <h3 className="topic-title">{topic.title}</h3>
      <p className="teacher-count">
        Есть данные: {total} из {students} учеников
      </p>
      <div
        className="stacked-bar"
        role="img"
        aria-label={`Из ${students} учеников: стоит повторить — ${topic.weak}, закрепляют — ${topic.improving}, освоили — ${topic.solid}, нет данных — ${Math.max(0, students - total)}`}
      >
        <span className="bar-weak" style={{ width: width(topic.weak) }} />
        <span className="bar-improving" style={{ width: width(topic.improving) }} />
        <span className="bar-solid" style={{ width: width(topic.solid) }} />
      </div>
      <dl className="teacher-legend">
        <div>
          <dt className="dot dot-weak">Стоит повторить</dt>
          <dd>{topic.weak}</dd>
        </div>
        <div>
          <dt className="dot dot-improving">Закрепляют</dt>
          <dd>{topic.improving}</dd>
        </div>
        <div>
          <dt className="dot dot-solid">Освоили</dt>
          <dd>{topic.solid}</dd>
        </div>
        <div>
          <dt className="dot dot-none">Нет данных</dt>
          <dd>{Math.max(0, students - total)}</dd>
        </div>
      </dl>
      {topic.top_error_type && (
        <p className="teacher-error">Частая ошибка: {topic.top_error_type.title}</p>
      )}
    </article>
  );
}
export function TeacherScreen() {
  const summary = useLoader("teacher", () => api.teacherSummary());
  const data = summary.data;
  return (
    <Screen label="Темы класса">
      <ScreenHeader
        title="Темы класса"
        subtitle={
          data?.school_class
            ? `${data.school_class.title} · ${countLabel(data.students_total, "ученик", "ученика", "учеников")}`
            : "Общая картина по темам"
        }
      />
      {summary.state === "loading" && <SkeletonCards count={3} height={160} />}
      {summary.state === "error" && (
        <ErrorState audience="teacher" error={summary.error} onRetry={summary.reload} />
      )}
      {data &&
        (!data.school_class ? (
          <EmptyState
            icon={<ChartIcon size={28} />}
            title="Класс не подключён"
            action={<ChatAction audience="teacher" />}
          >
            <p>Подключите класс в личном чате с ботом, чтобы посмотреть сводку.</p>
          </EmptyState>
        ) : !data.topics.length ? (
          <EmptyState icon={<ChartIcon size={28} />} title="Данных по темам пока нет">
            <p>
              Сводка появится после разборов и тестов учеников класса. Отсутствие данных не означает
              освоение темы.
            </p>
          </EmptyState>
        ) : (
          <>
            <section className="teacher-overview card">
              <span>Темы для повторения есть у</span>
              <strong>
                {data.students_with_gaps} из {data.students_total} учеников
              </strong>
              <p>В сводке только количества по темам, без имён и личных работ.</p>
            </section>
            <p className="footnote">
              Полная ширина полосы — весь класс. Незаполненная часть — ученики без данных по теме.
            </p>
            <section className="stack" aria-label="Распределение по темам">
              {[...data.topics]
                .sort(
                  (a, b) =>
                    b.weak - a.weak ||
                    b.improving - a.improving ||
                    a.title.localeCompare(b.title, "ru"),
                )
                .map((topic) => (
                  <TeacherTopicRow key={topic.code} topic={topic} students={data.students_total} />
                ))}
            </section>
          </>
        ))}
    </Screen>
  );
}
