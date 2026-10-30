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

const timeFormat = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });
const dayFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" });

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
  if (days <= 0) return "повторить сегодня";
  if (days === 1) return "повторить завтра";
  return `повторить через ${countLabel(days, "день", "дня", "дней")}`;
}

export interface ErrorCopy {
  title: string;
  text: string;
  retry: boolean;
}

export function describeError(error: unknown): ErrorCopy {
  const kind = error instanceof ApiError ? error.kind : "client";
  switch (kind) {
    case "auth":
      return {
        title: "Открой Ясно в MAX",
        text: "Приложение работает внутри чата с ботом. Зайди в MAX, открой чат с «Ясно» и нажми кнопку приложения.",
        retry: false,
      };
    case "forbidden":
      return {
        title: "Сюда нельзя",
        text: "Этот раздел доступен только учителю класса.",
        retry: false,
      };
    case "not_found":
      return {
        title: "Не нашли",
        text: "Похоже, этого больше нет. Вернись назад и попробуй ещё раз.",
        retry: false,
      };
    case "network":
      return {
        title: "Нет связи",
        text: "Проверь интернет — и попробуем ещё раз.",
        retry: true,
      };
    default:
      return {
        title: "Что-то пошло не так",
        text: "Мы уже разбираемся. Попробуй ещё раз через минуту.",
        retry: true,
      };
  }
}
