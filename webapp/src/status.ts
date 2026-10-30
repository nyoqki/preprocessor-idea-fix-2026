import type { Submission } from "./api/types";

export type Tone = "accent" | "weak" | "improving" | "solid" | "neutral";

export function describeSubmission(item: Submission): { label: string; tone: Tone } {
  switch (item.status) {
    case "queued":
    case "processing":
      return { label: "Проверяю решение…", tone: "accent" };
    case "needs_confirmation":
      return { label: "Подтверди распознанное в чате", tone: "improving" };
    case "failed":
      return { label: "Не получилось разобрать фото", tone: "neutral" };
    case "done":
      if (item.first_error_step !== null || item.error_type !== null) {
        return { label: item.error_title ?? "Нашёл ошибку", tone: "weak" };
      }
      return { label: "Ошибок не нашёл", tone: "solid" };
  }
}
