type Impact = "light" | "medium" | "heavy" | "rigid" | "soft";
type Notification = "error" | "success" | "warning";

interface MaxBackButton {
  show?: () => unknown;
  hide?: () => unknown;
  onClick?: (callback: () => void) => unknown;
  offClick?: (callback: () => void) => unknown;
}

interface MaxHaptics {
  impactOccurred?: (style: Impact, disableVibrationFallback?: boolean) => unknown;
  notificationOccurred?: (type: Notification, disableVibrationFallback?: boolean) => unknown;
  selectionChanged?: (disableVibrationFallback?: boolean) => unknown;
}

interface MaxWebApp {
  initData?: string;
  initDataUnsafe?: {
    start_param?: string;
    user?: { id: number; first_name?: string; last_name?: string; photo_url?: string };
  };
  platform?: string;
  version?: string;
  ready?: () => unknown;
  BackButton?: MaxBackButton;
  HapticFeedback?: MaxHaptics;
  openLink?: (url: string) => unknown;
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
  return isInsideMax() && Boolean(webApp()?.BackButton?.show);
}

export function showBackButton(onClick: () => void): () => void {
  const button = webApp()?.BackButton;
  if (!button || !isInsideMax()) {
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
  if (app?.openLink) {
    safely(() => app.openLink?.(url));
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}
