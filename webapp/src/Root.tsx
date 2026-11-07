import { lazy, Suspense, useLayoutEffect } from "react";

import { MaxUI } from "@maxhub/max-ui";

import { App } from "./App";
import { useColorScheme } from "./hooks";
import { platform } from "./max";

const Catalog = import.meta.env.DEV ? lazy(() => import("./dev/Catalog")) : () => null;

export function Root() {
  const scheme = useColorScheme();
  useLayoutEffect(() => {
    document.documentElement.dataset.scheme = scheme;
    document.documentElement.style.colorScheme = scheme;
  }, [scheme]);
  const os = platform() === "ios" ? "ios" : platform() === "android" ? "android" : undefined;
  return (
    <MaxUI
      colorScheme={scheme}
      {...(os ? { platform: os } : {})}
      className={scheme === "dark" ? "yasno yasno-dark" : "yasno"}
    >
      {import.meta.env.DEV && new URLSearchParams(location.search).has("catalog") ? (
        <Suspense fallback={<p>Загрузка каталога…</p>}>
          <Catalog />
        </Suspense>
      ) : (
        <App />
      )}
    </MaxUI>
  );
}
