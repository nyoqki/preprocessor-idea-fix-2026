import { useSyncExternalStore } from "react";

export type Route =
  | { name: "map" }
  | { name: "submissions" }
  | { name: "submission"; id: number }
  | { name: "quiz"; id: number }
  | { name: "class" }
  | { name: "teacher" };

export type Tab = "map" | "submissions" | "class" | "teacher";

const patterns: [RegExp, (match: RegExpMatchArray) => Route][] = [
  [/^\/?$/, () => ({ name: "map" })],
  [/^\/map$/, () => ({ name: "map" })],
  [/^\/submissions$/, () => ({ name: "submissions" })],
  [/^\/submissions\/(\d+)$/, (m) => ({ name: "submission", id: Number(m[1]) })],
  [/^\/quiz\/(\d+)$/, (m) => ({ name: "quiz", id: Number(m[1]) })],
  [/^\/class$/, () => ({ name: "class" })],
  [/^\/teacher$/, () => ({ name: "teacher" })],
];

export function parsePath(path: string): Route {
  for (const [pattern, build] of patterns) {
    const match = pattern.exec(path);
    if (match) {
      return build(match);
    }
  }
  return { name: "map" };
}

export function pathFor(route: Route): string {
  switch (route.name) {
    case "map":
      return "/map";
    case "submissions":
      return "/submissions";
    case "submission":
      return `/submissions/${route.id}`;
    case "quiz":
      return `/quiz/${route.id}`;
    case "class":
      return "/class";
    case "teacher":
      return "/teacher";
  }
}

export function tabOf(route: Route): Tab {
  switch (route.name) {
    case "submission":
      return "submissions";
    case "quiz":
      return "map";
    default:
      return route.name;
  }
}

export function parentOf(route: Route): Route | null {
  switch (route.name) {
    case "submission":
      return { name: "submissions" };
    case "quiz":
      return { name: "map" };
    default:
      return null;
  }
}

export function routeFromStartParam(param: string | null): Route | null {
  if (!param) {
    return null;
  }
  const match = /^(quiz|submission)_(\d{1,12})$/.exec(param);
  if (match) {
    const id = Number(match[2]);
    return match[1] === "quiz" ? { name: "quiz", id } : { name: "submission", id };
  }
  switch (param) {
    case "map":
    case "gaps":
      return { name: "map" };
    case "submissions":
    case "history":
      return { name: "submissions" };
    case "class":
    case "materials":
      return { name: "class" };
    case "teacher":
      return { name: "teacher" };
    default:
      return null;
  }
}

function currentPath(): string {
  return window.location.hash.replace(/^#/, "") || "/";
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("hashchange", callback);
  window.addEventListener("popstate", callback);
  return () => {
    window.removeEventListener("hashchange", callback);
    window.removeEventListener("popstate", callback);
  };
}

export function useRoute(): Route {
  const path = useSyncExternalStore(subscribe, currentPath, () => "/");
  return parsePath(path);
}

export function navigate(route: Route, options: { replace?: boolean } = {}): void {
  const target = `#${pathFor(route)}`;
  if (window.location.hash === target) {
    return;
  }
  if (options.replace) {
    window.history.replaceState(null, "", target);
  } else {
    window.history.pushState({ pushed: true }, "", target);
  }
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

function wasPushed(): boolean {
  const state: unknown = window.history.state;
  return typeof state === "object" && state !== null && "pushed" in state;
}

export function goBack(route: Route): void {
  if (wasPushed()) {
    window.history.back();
    return;
  }
  navigate(parentOf(route) ?? { name: "map" }, { replace: true });
}
