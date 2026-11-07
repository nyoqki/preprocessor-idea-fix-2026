import { ApiError } from "./api";

export function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

export function countLabel(count: number, one: string, few: string, many: string): string {
  return `${count} ${plural(count, one, few, many)}`;
}

const timeFormat = new Intl.DateTimeFormat("ru-RU", {
  hour: "2-digit",
  minute: "2-digit",
});
const dayFormat = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "long",
});

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

export function relativeDate(iso: string, now = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  const time = timeFormat.format(date);
  if (days === 0) return `сегодня, ${time}`;
  if (days === 1) return `вчера, ${time}`;
  return `${dayFormat.format(date)}, ${time}`;
}

export function untilDate(iso: string | null, now = new Date()): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  const days = Math.round((startOfDay(date) - startOfDay(now)) / 86_400_000);
  if (!Number.isFinite(days)) return null;
  if (days <= 0) return "повторить сегодня";
  if (days === 1) return "повторить завтра";
  return `повторить через ${countLabel(days, "день", "дня", "дней")}`;
}

export interface ErrorCopy {
  title: string;
  text: string;
  retry: boolean;
}

export function describeError(
  error: unknown,
  audience: "student" | "teacher" = "student",
): ErrorCopy {
  const teacher = audience === "teacher";
  const kind = error instanceof ApiError ? error.kind : "client";
  switch (kind) {
    case "auth":
      return {
        title: "Открой Ясно в MAX",
        text: teacher
          ? "Приложение работает внутри чата с ботом. Зайдите в MAX, откройте чат с «Ясно» и нажмите кнопку приложения."
          : "Приложение работает внутри чата с ботом. Зайди в MAX, открой чат с «Ясно» и нажми кнопку приложения.",
        retry: false,
      };
    case "forbidden":
      return {
        title: "Раздел для учителя",
        text: "Этот раздел доступен только учителю класса.",
        retry: false,
      };
    case "not_found":
      return {
        title: "Данные недоступны",
        text: teacher
          ? "Запись не найдена или доступ к ней закрыт. Вернитесь в раздел."
          : "Запись не найдена или доступ к ней закрыт. Вернись в раздел.",
        retry: false,
      };
    case "network":
      return {
        title: "Нет связи",
        text: teacher
          ? "Проверьте подключение к интернету и повторите загрузку."
          : "Проверь подключение к интернету и повтори загрузку.",
        retry: true,
      };
    default:
      return {
        title: "Не удалось загрузить данные",
        text: teacher
          ? "Попробуйте загрузить данные ещё раз."
          : "Попробуй загрузить данные ещё раз.",
        retry: true,
      };
  }
}
