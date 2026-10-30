import { MaxUI } from "@maxhub/max-ui";

import { App } from "./App";
import { useColorScheme } from "./hooks";
import { platform } from "./max";

export function Root() {
  const scheme = useColorScheme();
  const os = platform() === "ios" ? "ios" : platform() === "android" ? "android" : undefined;
  return (
    <MaxUI
      colorScheme={scheme}
      {...(os ? { platform: os } : {})}
      className={scheme === "dark" ? "yasno yasno-dark" : "yasno"}
    >
      <App />
    </MaxUI>
  );
}
