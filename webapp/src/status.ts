import type { GapStatus, Submission } from "./api/types";

export type Tone = "accent" | "weak" | "improving" | "solid" | "neutral";
export const TOPIC_LABEL: Record<GapStatus, string> = {
  weak: "Стоит повторить",
  improving: "Закрепляем",
  solid: "Освоено",
};

export function describeSubmission(item: Submission): {
  label: string;
  tone: Tone;
} {
  switch (item.status) {
    case "queued":
      return { label: "Фото в очереди", tone: "accent" };
    case "processing":
      return { label: "Разбираем решение", tone: "accent" };
    case "needs_confirmation":
      return { label: "Нужно уточнить запись", tone: "improving" };
    case "failed":
      return { label: "Не удалось разобрать фото", tone: "neutral" };
    case "done":
      switch (item.verdict) {
        case "correct":
          return { label: "Решение проверено", tone: "solid" };
        case "error":
          return {
            label:
              item.first_error_step === null
                ? "Проверь решение"
                : `Проверь шаг ${item.first_error_step + 1}`,
            tone: "weak",
          };
        case "incomplete":
          return { label: "Решение ещё не закончено", tone: "improving" };
        case "review":
          return { label: "Нужно пояснить шаг", tone: "improving" };
        default:
          return { label: "Результат проверки недоступен", tone: "neutral" };
      }
  }
}
