import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

export type Loadable<T> =
  | { state: "loading"; data: null; error: null }
  | { state: "ready"; data: T; error: null }
  | { state: "error"; data: null; error: unknown };

const LOADING = { state: "loading", data: null, error: null } as const;

export function useLoader<T>(
  key: string,
  loader: () => Promise<T>,
): Loadable<T> & { reload: () => void; setData: (data: T) => void } {
  const loaderRef = useRef(loader);
  const pendingRef = useRef<{ token: string; promise: Promise<T> } | null>(
    null,
  );
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    token: string;
    value: Loadable<T>;
  } | null>(null);
  const token = `${key}#${attempt}`;

  useLayoutEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    let cancelled = false;
    // Reuse the in-flight request when StrictMode replays this effect.
    if (pendingRef.current?.token !== token) {
      pendingRef.current = {
        token,
        promise: Promise.resolve().then(() => loaderRef.current()),
      };
    }
    pendingRef.current.promise.then(
      (data) => {
        if (!cancelled)
          setResult({ token, value: { state: "ready", data, error: null } });
      },
      (error: unknown) => {
        if (!cancelled)
          setResult({ token, value: { state: "error", data: null, error } });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [token]);

  const reload = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);
  const setData = useCallback(
    (data: T) => {
      setResult({ token, value: { state: "ready", data, error: null } });
    },
    [token],
  );

  const value: Loadable<T> = result?.token === token ? result.value : LOADING;
  return { ...value, reload, setData };
}

export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(value);
    }, ms);
    return () => {
      clearTimeout(timer);
    };
  }, [value, ms]);
  return debounced;
}

const darkQuery = "(prefers-color-scheme: dark)";

function subscribeScheme(callback: () => void): () => void {
  const media = window.matchMedia(darkQuery);
  media.addEventListener("change", callback);
  window.addEventListener("yasno-theme", callback);
  return () => {
    media.removeEventListener("change", callback);
    window.removeEventListener("yasno-theme", callback);
  };
}

export function useColorScheme(): "light" | "dark" {
  return useSyncExternalStore(
    subscribeScheme,
    () => {
      const demo = import.meta.env.DEV
        ? new URLSearchParams(location.search).get("theme")
        : null;
      return demo === "dark" || demo === "light"
        ? demo
        : window.matchMedia(darkQuery).matches
          ? "dark"
          : "light";
    },
    () => "light",
  );
}

export function useOnline(): boolean {
  return useSyncExternalStore(
    (callback) => {
      window.addEventListener("online", callback);
      window.addEventListener("offline", callback);
      return () => {
        window.removeEventListener("online", callback);
        window.removeEventListener("offline", callback);
      };
    },
    () => navigator.onLine,
    () => true,
  );
}
