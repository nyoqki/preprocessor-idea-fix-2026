import { initData } from "../max";
import type {
  ActiveQuiz,
  AnswerResult,
  GapMap,
  MaterialPage,
  Me,
  Page,
  Quiz,
  Submission,
  SubmissionDetail,
  TeacherSummary,
} from "./types";

export type ErrorKind = "auth" | "forbidden" | "not_found" | "network" | "server" | "client";

export class ApiError extends Error {
  readonly kind: ErrorKind;
  readonly status: number;

  constructor(kind: ErrorKind, status: number, message: string) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

const TIMEOUT_MS = 15000;
const BASE = "/api/v1";

function kindFor(status: number): ErrorKind {
  if (status === 401) return "auth";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status >= 500) return "server";
  return "client";
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function once<T>(path: string, init: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort();
  }, TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        Authorization: `tma ${initData()}`,
        ...(init.body ? { "Content-Type": "application/json" } : {}),
      },
    });
  } catch {
    throw new ApiError("network", 0, "network");
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    throw new ApiError(kindFor(response.status), response.status, `http ${response.status}`);
  }
  return (await response.json()) as T;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const retries = init.method && init.method !== "GET" ? 1 : 2;
  for (let attempt = 0; ; attempt++) {
    try {
      return await once<T>(path, init);
    } catch (error) {
      const retryable =
        error instanceof ApiError && (error.kind === "network" || error.kind === "server");
      if (!retryable || attempt >= retries) {
        throw error;
      }
      await wait(400 * 2 ** attempt);
    }
  }
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export interface Api {
  me(): Promise<Me>;
  gaps(): Promise<GapMap>;
  submissions(cursor?: string | null): Promise<Page<Submission>>;
  submission(id: number): Promise<SubmissionDetail>;
  activeQuiz(): Promise<ActiveQuiz>;
  quiz(id: number): Promise<Quiz>;
  answer(quizId: number, itemId: number, choiceIndex: number): Promise<AnswerResult>;
  materials(q: string, cursor?: string | null): Promise<MaterialPage>;
  teacherSummary(): Promise<TeacherSummary>;
}

export const httpApi: Api = {
  me: () => request<Me>("/me"),
  gaps: () => request<GapMap>("/gaps"),
  submissions: (cursor) => request<Page<Submission>>(`/submissions${query({ cursor })}`),
  submission: (id) => request<SubmissionDetail>(`/submissions/${id}`),
  activeQuiz: () => request<ActiveQuiz>("/quizzes/active"),
  quiz: (id) => request<Quiz>(`/quizzes/${id}`),
  answer: (quizId, itemId, choiceIndex) =>
    request<AnswerResult>(`/quizzes/${quizId}/items/${itemId}/answer`, {
      method: "POST",
      body: JSON.stringify({ choice_index: choiceIndex }),
    }),
  materials: (q, cursor) => request<MaterialPage>(`/materials${query({ q, cursor })}`),
  teacherSummary: () => request<TeacherSummary>("/teacher/summary"),
};
