import { ApiError, type Api } from "./client";
import type {
  AnswerResult,
  GapMap,
  Material,
  Me,
  Quiz,
  Submission,
  SubmissionDetail,
  TeacherSummary,
} from "./types";

const notebookLines = ["x² − 5x + 6 = 0", "D = 25 + 24 = 49", "x = (5 ± 7) / 2", "x₁ = 6, x₂ = −1"];

function notebookImage(lines: string[], errorIndex: number | null): string {
  const rows = lines
    .map((line, index) => {
      const y = 120 + index * 110;
      const color = index === errorIndex ? "#1d1a6b" : "#23205a";
      return `<text x="70" y="${y}" font-family="Georgia, serif" font-style="italic" font-size="54" fill="${color}">${line}</text>`;
    })
    .join("");
  const grid = Array.from({ length: 30 }, (_, i) => {
    const pos = i * 30;
    return `<line x1="0" y1="${pos}" x2="900" y2="${pos}" stroke="#cfe0f3" stroke-width="2"/><line x1="${pos}" y1="0" x2="${pos}" y2="560" stroke="#cfe0f3" stroke-width="2"/>`;
  }).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="560" viewBox="0 0 900 560"><rect width="900" height="560" fill="#fbfbf7"/>${grid}${rows}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function bboxFor(index: number) {
  return { x: 0.06, y: (60 + index * 110) / 560, width: 0.7, height: 80 / 560 };
}

const now = Date.now();
const hoursAgo = (hours: number) => new Date(now - hours * 3_600_000).toISOString();

const me: Me = {
  id: 1,
  first_name: "Аня",
  last_name: null,
  role: "student",
  grade: 9,
  consent_status: "granted",
  school_class: { id: 1, title: "9Б", grade: 9 },
};

const gaps: GapMap = {
  summary: { weak: 2, improving: 1, solid: 1 },
  topics: [
    {
      code: "alg.quadratic_eq",
      title: "Квадратные уравнения",
      status: "weak",
      mistakes_total: 3,
      correct_total: 1,
      last_mistake_at: hoursAgo(5),
      next_review_at: hoursAgo(-40),
      error_types: [
        { code: "sign", title: "Ошибка в знаке", count: 2 },
        { code: "lost_root", title: "Потерян корень", count: 1 },
      ],
    },
    {
      code: "arith.fractions",
      title: "Действия с дробями",
      status: "weak",
      mistakes_total: 2,
      correct_total: 0,
      last_mistake_at: hoursAgo(30),
      next_review_at: hoursAgo(-20),
      error_types: [{ code: "fractions", title: "Действия с дробями", count: 2 }],
    },
    {
      code: "alg.roots",
      title: "Квадратные корни",
      status: "improving",
      mistakes_total: 1,
      correct_total: 3,
      last_mistake_at: hoursAgo(80),
      next_review_at: hoursAgo(-100),
      error_types: [{ code: "roots", title: "Свойства корней", count: 1 }],
    },
    {
      code: "alg.linear_ineq",
      title: "Линейные неравенства",
      status: "solid",
      mistakes_total: 1,
      correct_total: 5,
      last_mistake_at: hoursAgo(300),
      next_review_at: null,
      error_types: [
        {
          code: "inequality_flip",
          title: "Знак неравенства при умножении на отрицательное",
          count: 1,
        },
      ],
    },
  ],
};

const submissionDetails: SubmissionDetail[] = [
  {
    id: 41,
    created_at: hoursAgo(5),
    finished_at: hoursAgo(5),
    status: "done",
    verdict: "error",
    topic_code: "alg.quadratic_eq",
    topic_title: "Квадратные уравнения",
    error_type: "sign",
    error_title: "Ошибка в знаке",
    first_error_step: 1,
    image_url: notebookImage(notebookLines, 1),
    task: "Реши уравнение x² − 5x + 6 = 0",
    lines: notebookLines.map((display, index) => ({
      index,
      latex: display,
      display,
      confidence: index === 3 ? 0.82 : 0.97,
      bbox: bboxFor(index),
      is_error: index === 1,
    })),
    analysis: {
      status: "error",
      first_error_step: 1,
      error_type: "sign",
      error_title: "Ошибка в знаке",
      hint: "Посмотри внимательно на формулу дискриминанта: D = b² − 4ac. Какой знак стоит перед 4ac и чему равно c?",
    },
    error_bbox: bboxFor(1),
  },
  {
    id: 40,
    created_at: hoursAgo(1),
    finished_at: null,
    status: "processing",
    verdict: null,
    topic_code: null,
    topic_title: null,
    error_type: null,
    error_title: null,
    first_error_step: null,
    image_url: null,
    task: null,
    lines: [],
    analysis: null,
    error_bbox: null,
  },
  {
    id: 39,
    created_at: hoursAgo(26),
    finished_at: hoursAgo(26),
    status: "done",
    verdict: "correct",
    topic_code: "alg.linear_ineq",
    topic_title: "Линейные неравенства",
    error_type: null,
    error_title: null,
    first_error_step: null,
    image_url: notebookImage(["3x − 7 < 2", "3x < 9", "x < 3"], null),
    task: "Реши неравенство 3x − 7 < 2",
    lines: ["3x − 7 < 2", "3x < 9", "x < 3"].map((display, index) => ({
      index,
      latex: display,
      display,
      confidence: 0.98,
      bbox: bboxFor(index),
      is_error: false,
    })),
    analysis: {
      status: "correct",
      first_error_step: null,
      error_type: null,
      error_title: null,
      hint: null,
    },
    error_bbox: null,
  },
  {
    id: 38,
    created_at: hoursAgo(50),
    finished_at: hoursAgo(50),
    status: "needs_confirmation",
    verdict: null,
    topic_code: "arith.fractions",
    topic_title: "Действия с дробями",
    error_type: null,
    error_title: null,
    first_error_step: null,
    image_url: null,
    task: null,
    lines: [],
    analysis: null,
    error_bbox: null,
  },
  {
    id: 37,
    created_at: hoursAgo(72),
    finished_at: hoursAgo(72),
    status: "failed",
    verdict: null,
    topic_code: null,
    topic_title: null,
    error_type: null,
    error_title: null,
    first_error_step: null,
    image_url: null,
    task: null,
    lines: [],
    analysis: null,
    error_bbox: null,
  },
];

const quiz: Quiz = {
  id: 7,
  reason: "exam",
  status: "active",
  created_at: hoursAgo(2),
  total: 5,
  answered: 0,
  correct: 0,
  topic_titles: ["Квадратные уравнения", "Действия с дробями"],
  items: [
    {
      prompt: "Чему равен дискриминант уравнения x² − 5x + 6 = 0?",
      choices: ["49", "1", "−1", "25"],
      correct: 1,
    },
    {
      prompt: "Сколько корней у уравнения x² + 4 = 0?",
      choices: ["Два", "Один", "Ни одного", "Бесконечно много"],
      correct: 2,
    },
    {
      prompt: "Вычисли: 2/3 + 1/6",
      choices: ["3/9", "5/6", "1/2", "3/6"],
      correct: 1,
    },
    {
      prompt: "Корни уравнения x² − 9 = 0",
      choices: ["x = 3", "x = 9", "x = ±3", "x = −3"],
      correct: 2,
    },
    {
      prompt: "Упрости: (3/4) : (9/8)",
      choices: ["27/32", "2/3", "3/2", "1/6"],
      correct: 1,
    },
  ].map((item, position) => ({
    id: 100 + position,
    position,
    topic_code: position === 2 || position === 4 ? "arith.fractions" : "alg.quadratic_eq",
    topic_title: position === 2 || position === 4 ? "Действия с дробями" : "Квадратные уравнения",
    prompt: item.prompt,
    choices: item.choices.map((text, index) => ({ index, text })),
    from_gap_map: position !== 3,
    answered_index: null,
    correct_index: null,
    is_correct: null,
  })),
};

const correctAnswers = new Map<number, number>([
  [100, 1],
  [101, 2],
  [102, 1],
  [103, 2],
  [104, 1],
]);

const explanations = new Map<number, string>([
  [100, "Вспомни: D = b² − 4ac, а c здесь положительное."],
  [101, "Квадрат числа не бывает отрицательным — попробуй выразить x²."],
  [102, "Приведи дроби к общему знаменателю 6."],
  [103, "Не забывай, что у квадрата два корня: положительный и отрицательный."],
  [104, "Деление на дробь — это умножение на перевёрнутую дробь."],
]);

const materials: Material[] = [
  {
    id: 3,
    title: "Конспект: теорема Виета",
    snippet:
      "Если x₁ и x₂ — корни уравнения x² + px + q = 0, то x₁ + x₂ = −p, а x₁·x₂ = q. Удобно для проверки корней без вычислений.",
    topic_titles: ["Квадратные уравнения"],
    created_at: hoursAgo(20),
  },
  {
    id: 2,
    title: "Памятка по дробям",
    snippet:
      "Чтобы сложить дроби, приведи их к общему знаменателю. При делении умножай на обратную дробь.",
    topic_titles: ["Действия с дробями"],
    created_at: hoursAgo(70),
  },
  {
    id: 1,
    title: "Дискриминант",
    snippet: "D = b² − 4ac. Если D > 0 — два корня, D = 0 — один, D < 0 — корней нет.",
    topic_titles: ["Квадратные уравнения"],
    created_at: hoursAgo(120),
  },
];

const teacher: TeacherSummary = {
  school_class: { id: 1, title: "9Б", grade: 9 },
  students_total: 27,
  students_with_gaps: 14,
  topics: [
    {
      code: "alg.quadratic_eq",
      title: "Квадратные уравнения",
      weak: 9,
      improving: 4,
      solid: 2,
      top_error_type: { code: "sign", title: "Ошибка в знаке", count: 12 },
    },
    {
      code: "arith.fractions",
      title: "Действия с дробями",
      weak: 5,
      improving: 3,
      solid: 6,
      top_error_type: {
        code: "fractions",
        title: "Действия с дробями",
        count: 7,
      },
    },
    {
      code: "alg.roots",
      title: "Квадратные корни",
      weak: 2,
      improving: 5,
      solid: 4,
      top_error_type: { code: "roots", title: "Свойства корней", count: 3 },
    },
  ],
};

function delay<T>(value: T, ms = 450): Promise<T> {
  if (!navigator.onLine) return Promise.reject(new ApiError("network", 0, "offline"));
  return new Promise((resolve) =>
    setTimeout(() => {
      resolve(structuredClone(value));
    }, ms),
  );
}

function toSummary(detail: SubmissionDetail): Submission {
  return {
    id: detail.id,
    created_at: detail.created_at,
    status: detail.status,
    verdict: detail.verdict,
    topic_code: detail.topic_code,
    topic_title: detail.topic_title,
    error_type: detail.error_type,
    error_title: detail.error_title,
    first_error_step: detail.first_error_step,
    image_url: detail.image_url,
  };
}

function quizCounts(): void {
  const answered = quiz.items.filter((item) => item.answered_index !== null);
  quiz.answered = answered.length;
  quiz.correct = answered.filter((item) => item.is_correct).length;
  quiz.status = quiz.answered === quiz.total ? "completed" : "active";
}

const baseMockApi: Api = {
  me: () => delay(me),
  gaps: () => delay(gaps),
  submissions: () => delay({ items: submissionDetails.map(toSummary), next_cursor: null }),
  submission: (id) => {
    const found = submissionDetails.find((item) => item.id === id);
    return found ? delay(found) : Promise.reject(new ApiError("not_found", 404, "not found"));
  },
  activeQuiz: () => {
    const summary = {
      id: quiz.id,
      reason: quiz.reason,
      status: quiz.status,
      created_at: quiz.created_at,
      total: quiz.total,
      answered: quiz.answered,
      correct: quiz.correct,
      topic_titles: quiz.topic_titles,
    };
    return delay({ quiz: quiz.status === "active" ? summary : null });
  },
  quiz: (id) =>
    id === quiz.id ? delay(quiz) : Promise.reject(new ApiError("not_found", 404, "not found")),
  answer: (_quizId, itemId, choiceIndex) => {
    const item = quiz.items.find((candidate) => candidate.id === itemId);
    const correctIndex = correctAnswers.get(itemId);
    if (!item || correctIndex === undefined) {
      return Promise.reject(new ApiError("not_found", 404, "not found"));
    }
    const alreadyAnswered = item.answered_index !== null;
    if (!alreadyAnswered) {
      item.answered_index = choiceIndex;
      item.correct_index = correctIndex;
      item.is_correct = choiceIndex === correctIndex;
      quizCounts();
    }
    const chosen = item.answered_index ?? choiceIndex;
    const result: AnswerResult = {
      item_id: itemId,
      chosen_index: chosen,
      correct_index: correctIndex,
      is_correct: chosen === correctIndex,
      explanation: chosen === correctIndex ? null : (explanations.get(itemId) ?? null),
      already_answered: alreadyAnswered,
      quiz_status: quiz.status,
      answered: quiz.answered,
      total: quiz.total,
      correct: quiz.correct,
    };
    try {
      sessionStorage.setItem(
        storageKey,
        JSON.stringify(
          quiz.items.map((entry) => ({
            id: entry.id,
            chosen: entry.answered_index,
          })),
        ),
      );
    } catch {}
    return delay(result, 650);
  },
  materials: (q) => {
    const needle = q.trim().toLowerCase();
    const items = needle
      ? materials.filter((item) =>
          `${item.title ?? ""} ${item.snippet}`.toLowerCase().includes(needle),
        )
      : materials;
    return delay({ has_class: true, items, next_cursor: null }, 300);
  },
  teacherSummary: () => delay(teacher),
};

const options = new URLSearchParams(location.search);
const scenario = options.get("scenario") ?? "default";
const storageKey = `yasno-demo-quiz:${scenario}`;
try {
  const stored: unknown = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
  if (Array.isArray(stored))
    for (const value of stored) {
      const row: unknown = value;
      if (!row || typeof row !== "object" || !("id" in row) || !("chosen" in row)) continue;
      const item = quiz.items.find((entry) => entry.id === row.id);
      const chosen: unknown = row.chosen;
      if (
        item &&
        typeof chosen === "number" &&
        item.choices.some((choice) => choice.index === chosen)
      ) {
        item.answered_index = chosen;
        item.correct_index = correctAnswers.get(item.id) ?? null;
        item.is_correct = chosen === item.correct_index;
      }
    }
} catch {}
quizCounts();
if (scenario === "completed") {
  for (const item of quiz.items) {
    item.answered_index = correctAnswers.get(item.id) ?? 0;
    item.correct_index = item.answered_index;
    item.is_correct = true;
  }
  quizCounts();
}
if (scenario === "expired") quiz.status = "expired";
const failed = new Set<string>();
async function before(operation: string) {
  if (scenario === "loading" && operation !== "me")
    await new Promise((resolve) => setTimeout(resolve, 15000));
  if (
    scenario === "auth" ||
    (scenario === "forbidden" && operation !== "me") ||
    (scenario === "not-found" && ["submission", "quiz"].includes(operation))
  ) {
    const status = scenario === "auth" ? 401 : scenario === "forbidden" ? 403 : 404;
    throw new ApiError(
      status === 401 ? "auth" : status === 403 ? "forbidden" : "not_found",
      status,
      "demo",
    );
  }
  if (
    ((scenario === "error" && operation !== "me") ||
      (scenario === "quiz-error" && operation === "active")) &&
    !failed.has(operation)
  ) {
    failed.add(operation);
    await new Promise((resolve) => setTimeout(resolve, 350));
    throw new ApiError("network", 0, "demo");
  }
}
export const mockApi: Api = {
  me: async () => {
    await before("me");
    return delay({
      ...me,
      role: options.get("role") === "teacher" ? "teacher" : "student",
      school_class: scenario === "no-class" ? null : me.school_class,
    });
  },
  gaps: async () => {
    await before("gaps");
    if (scenario === "empty")
      return delay({
        topics: [],
        summary: { weak: 0, improving: 0, solid: 0 },
      });
    const data = structuredClone(gaps);
    if (scenario === "long" && data.topics[0])
      data.topics[0].title =
        "Рациональные уравнения с параметрами и преобразование алгебраических выражений";
    return delay(data);
  },
  activeQuiz: async () => {
    await before("active");
    return scenario === "no-test" || scenario === "empty"
      ? delay({ quiz: null })
      : baseMockApi.activeQuiz();
  },
  submissions: async (cursor) => {
    await before("submissions");
    if (scenario === "empty") return delay({ items: [], next_cursor: null });
    if (scenario === "pagination-error") {
      if (cursor && !failed.has("history-more")) {
        failed.add("history-more");
        throw new ApiError("network", 0, "demo");
      }
      return delay({
        items: submissionDetails.slice(cursor ? 2 : 0, cursor ? undefined : 2).map(toSummary),
        next_cursor: cursor ? null : "2",
      });
    }
    return baseMockApi.submissions(cursor);
  },
  submission: async (id) => {
    await before("submission");
    const item = await baseMockApi.submission(id);
    const status = (
      {
        queued: "queued",
        processing: "processing",
        confirmation: "needs_confirmation",
        failed: "failed",
      } as Record<string, SubmissionDetail["status"] | undefined>
    )[scenario];
    if (status) {
      item.status = status;
      item.verdict = null;
      item.analysis = null;
      item.first_error_step = null;
    }
    if (["correct", "review", "incomplete", "unknown"].includes(scenario)) {
      item.status = "done";
      item.verdict = scenario === "unknown" ? null : scenario;
      item.first_error_step = null;
      item.error_type = null;
      item.error_title = null;
      item.error_bbox = null;
      item.lines = item.lines.map((line) => ({ ...line, is_error: false }));
      item.analysis = null;
    }
    if (scenario === "photo-error") item.image_url = "/__unavailable-photo.png";
    if (scenario === "long" && item.lines[0]) {
      item.topic_title =
        "Рациональные уравнения с параметрами и преобразование алгебраических выражений";
      item.lines[0].display =
        "(x² − 5x + 6) / (x² − 9) + √(x² + 2x + 1) = (x − 2)(x − 3) / ((x − 3)(x + 3))";
    }
    return item;
  },
  quiz: async (id) => {
    await before("quiz");
    if (scenario === "empty") {
      const data = await baseMockApi.quiz(id);
      return { ...data, items: [], total: 0 };
    }
    return baseMockApi.quiz(id);
  },
  answer: async (quizId, itemId, index) => {
    if (["answer-error", "answer-saved"].includes(scenario) && !failed.has("answer")) {
      failed.add("answer");
      if (scenario === "answer-saved") await baseMockApi.answer(quizId, itemId, index);
      await new Promise((resolve) => setTimeout(resolve, 400));
      throw new ApiError("network", 0, "demo");
    }
    return baseMockApi.answer(quizId, itemId, index);
  },
  materials: async (q, cursor) => {
    await before("materials");
    if (scenario === "no-class") return delay({ has_class: false, items: [], next_cursor: null });
    if (scenario === "empty") return delay({ has_class: true, items: [], next_cursor: null });
    const data = await baseMockApi.materials(q);
    if (scenario === "pagination-error" && !q) {
      if (cursor && !failed.has("materials-more")) {
        failed.add("materials-more");
        throw new ApiError("network", 0, "demo");
      }
      return {
        ...data,
        items: data.items.slice(cursor ? 2 : 0, cursor ? undefined : 2),
        next_cursor: cursor ? null : "2",
      };
    }
    return data;
  },
  teacherSummary: async () => {
    await before("teacher");
    const data = await baseMockApi.teacherSummary();
    if (scenario === "no-class")
      return {
        ...data,
        school_class: null,
        topics: [],
        students_total: 0,
        students_with_gaps: 0,
      };
    if (scenario === "empty") return { ...data, topics: [], students_with_gaps: 0 };
    return data;
  },
};
