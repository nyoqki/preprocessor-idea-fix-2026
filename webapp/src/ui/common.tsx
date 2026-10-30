import { Button, Typography } from "@maxhub/max-ui";
import type { ReactNode } from "react";

import { describeError } from "../format";
import { hasBackButton } from "../max";
import { ArrowLeftIcon } from "./icons";

export function Screen({ children, label }: { children: ReactNode; label: string }) {
  return (
    <main className="screen" aria-label={label}>
      {children}
    </main>
  );
}

export function ScreenHeader({
  title,
  subtitle,
  onBack,
}: {
  title: string;
  subtitle?: ReactNode;
  onBack?: () => void;
}) {
  const showBack = onBack !== undefined && !hasBackButton();
  return (
    <header className="screen-header">
      {showBack && (
        <button type="button" className="back-link" onClick={onBack}>
          <ArrowLeftIcon size={20} />
          <span>Назад</span>
        </button>
      )}
      <Typography.Headline variant="large-strong" asChild>
        <h1 className="screen-title">{title}</h1>
      </Typography.Headline>
      {subtitle && <p className="screen-subtitle">{subtitle}</p>}
    </header>
  );
}

export function Skeleton({ height = 16, width = "100%", radius = 10 }: {
  height?: number;
  width?: number | string;
  radius?: number;
}) {
  return <span className="skeleton" style={{ height, width, borderRadius: radius }} />;
}

export function SkeletonCards({ count = 3, height = 92 }: { count?: number; height?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Загружаем">
      {Array.from({ length: count }, (_, index) => (
        <div className="card skeleton-card" key={index} style={{ minHeight: height }}>
          <Skeleton width="55%" height={18} />
          <Skeleton width="35%" height={14} />
        </div>
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const copy = describeError(error);
  return (
    <div className="state" role="alert">
      <div className="state-emoji" aria-hidden="true">
        {copy.retry ? "📡" : "🔒"}
      </div>
      <Typography.Title variant="medium-strong" asChild>
        <h2 className="state-title">{copy.title}</h2>
      </Typography.Title>
      <p className="state-text">{copy.text}</p>
      {copy.retry && onRetry && (
        <Button size="medium" variant="primary" onClick={onRetry}>
          Попробовать ещё раз
        </Button>
      )}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="state">
      <div className="state-icon" aria-hidden="true">
        {icon}
      </div>
      <Typography.Title variant="medium-strong" asChild>
        <h2 className="state-title">{title}</h2>
      </Typography.Title>
      <div className="state-text">{children}</div>
      {action}
    </div>
  );
}

export function Chip({
  children,
  tone = "accent",
}: {
  children: ReactNode;
  tone?: "accent" | "weak" | "improving" | "solid" | "neutral";
}) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}
