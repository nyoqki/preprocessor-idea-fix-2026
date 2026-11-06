type Impact = "light" | "medium" | "heavy" | "rigid" | "soft";
type Notification = "error" | "success" | "warning";

interface MaxBackButton {
  show?: () => unknown;
  hide?: () => unknown;
  onClick?: (callback: () => void) => unknown;
  offClick?: (callback: () => void) => unknown;
}

interface MaxHaptics {
  impactOccurred?: (
    style: Impact,
    disableVibrationFallback?: boolean,
  ) => unknown;
  notificationOccurred?: (
    type: Notification,
    disableVibrationFallback?: boolean,
  ) => unknown;
  selectionChanged?: (disableVibrationFallback?: boolean) => unknown;
}

interface MaxWebApp {
  initData?: string;
  initDataUnsafe?: {
    start_param?: string;
    user?: {
      id: number;
      first_name?: string;
      last_name?: string;
      photo_url?: string;
    };
  };
  platform?: string;
  version?: string;
  ready?: () => unknown;
  BackButton?: MaxBackButton;
  HapticFeedback?: MaxHaptics;
  openLink?: (url: string) => unknown;
  openMaxLink?: (url: string) => unknown;
  getViewportSize?: () => Promise<{ width: string; height: string }>;
}

declare global {
  interface Window {
    WebApp?: MaxWebApp;
  }
}

function webApp(): MaxWebApp | undefined {
  return typeof window === "undefined" ? undefined : window.WebApp;
}

function safely(action: () => unknown): void {
  try {
    const result = action();
    if (result instanceof Promise) {
      result.catch(() => undefined);
    }
  } catch {
    return;
  }
}

export function initData(): string {
  return webApp()?.initData ?? "";
}

export function platform(): string {
  return webApp()?.platform ?? "web";
}

export function isInsideMax(): boolean {
  return initData().length > 0;
}

export function startParam(): string | null {
  const fromMax = webApp()?.initDataUnsafe?.start_param;
  if (fromMax) {
    return fromMax;
  }
  const fromUrl = new URLSearchParams(window.location.search).get("startapp");
  return fromUrl && /^[A-Za-z0-9_-]{1,512}$/.test(fromUrl) ? fromUrl : null;
}

export function ready(): void {
  safely(() => webApp()?.ready?.());
}

function hapticsAvailable(): boolean {
  const current = platform();
  return current === "ios" || current === "android";
}

export const haptics = {
  impact(style: Impact = "light"): void {
    if (hapticsAvailable()) {
      safely(() => webApp()?.HapticFeedback?.impactOccurred?.(style));
    }
  },
  notify(type: Notification): void {
    if (hapticsAvailable()) {
      safely(() => webApp()?.HapticFeedback?.notificationOccurred?.(type));
    }
  },
  selection(): void {
    if (hapticsAvailable()) {
      safely(() => webApp()?.HapticFeedback?.selectionChanged?.());
    }
  },
};

export function hasBackButton(): boolean {
  return (
    isInsideMax() &&
    Boolean(
      webApp()?.BackButton?.show &&
        webApp()?.BackButton?.onClick &&
        webApp()?.BackButton?.offClick,
    )
  );
}

export function showBackButton(onClick: () => void): () => void {
  const button = webApp()?.BackButton;
  if (!button || !hasBackButton()) {
    return () => undefined;
  }
  safely(() => button.onClick?.(onClick));
  safely(() => button.show?.());
  return () => {
    safely(() => button.offClick?.(onClick));
    safely(() => button.hide?.());
  };
}

export function openLink(url: string): void {
  const app = webApp();
  if (new URL(url).hostname === "max.ru" && app?.openMaxLink) {
    safely(() => app.openMaxLink?.(url));
    return;
  }
  if (app?.openLink) {
    safely(() => app.openLink?.(url));
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

// Optional public build configuration; never infer or expose the server bot token.
export function botUrl(): string | null {
  const username: unknown = import.meta.env.VITE_BOT_USERNAME;
  return typeof username === "string" && /^[A-Za-z0-9_]{3,64}$/.test(username)
    ? `https://max.ru/${username}`
    : null;
}

export function observeViewport(): () => void {
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const update = () => {
    const viewport = window.visualViewport;
    const editing = document.activeElement instanceof HTMLInputElement;
    document.documentElement.dataset.keyboard = String(
      Boolean(
        editing && viewport && window.innerHeight - viewport.height > 150,
      ),
    );
    const app = webApp();
    if (isInsideMax() && app?.getViewportSize) {
      try {
        void app
          .getViewportSize()
          .then(({ height }) => {
            const pixels = Number.parseFloat(height);
            if (!disposed && Number.isFinite(pixels) && pixels > 0) {
              document.documentElement.style.setProperty(
                "--yasno-viewport-height",
                `${pixels}px`,
              );
            }
          })
          .catch(() => undefined);
      } catch {
        /* Older clients use CSS dynamic viewport units. */
      }
    }
  };
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(update, 120);
  };
  update();
  window.addEventListener("resize", schedule);
  window.visualViewport?.addEventListener("resize", schedule);
  document.addEventListener("focusout", schedule);
  return () => {
    disposed = true;
    clearTimeout(timer);
    window.removeEventListener("resize", schedule);
    window.visualViewport?.removeEventListener("resize", schedule);
    document.removeEventListener("focusout", schedule);
    delete document.documentElement.dataset.keyboard;
    document.documentElement.style.removeProperty("--yasno-viewport-height");
  };
}
