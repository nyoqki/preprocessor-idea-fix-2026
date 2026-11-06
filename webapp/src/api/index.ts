import { httpApi, type Api } from "./client";

export const isMock = import.meta.env.DEV && import.meta.env.VITE_MOCK === "1";

export const api: Api =
  import.meta.env.DEV && import.meta.env.VITE_MOCK === "1"
    ? (await import("./mock")).mockApi
    : httpApi;

export { ApiError } from "./client";
export type { Api, ErrorKind } from "./client";
