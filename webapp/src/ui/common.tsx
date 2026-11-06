import { Button, Typography, type ButtonProps } from "@maxhub/max-ui";
import { useEffect, useRef, type ReactNode } from "react";

import { describeError } from "../format";
import { botUrl, hasBackButton, openLink } from "../max";
import { ArrowLeftIcon, ChecksIcon } from "./icons";

export function Action({
  variant = "primary",
  className = "",
  loading,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <Button
      {...props}
      variant={variant}
      loading={loading}
      disabled={disabled || loading}
      aria-label={
        props["aria-label"] ??
        (loading && typeof props.children === "string"
          ? props.children
          : undefined)
      }
      aria-busy={loading || undefined}
      className={`action action-${variant} ${className}`}
      innerClassNames={{ content: "action-content", spinner: "action-spinner" }}
    />
  );
}

export function ChatAction({
  primary = false,
  audience = "student",
}: {
  primary?: boolean;
  audience?: "student" | "teacher";
}) {
  const url = botUrl();
  return url ? (
    <Action
      size="large"
      variant={primary ? "primary" : "secondary"}
      stretched
      onClick={() => {
        openLink(url);
      }}
    >
      Открыть чат
    </Action>
  ) : (
    <p className="chat-note">
      {audience === "teacher"
        ? "Вернитесь в личный чат с ботом «Ясно», чтобы продолжить."
        : "Вернись в личный чат с ботом «Ясно», чтобы продолжить."}
    </p>
  );
}

export function Screen({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
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
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);
  return (
    <header className="screen-header">
      {onBack && !hasBackButton() && (
        <button type="button" className="back-link" onClick={onBack}>
          <ArrowLeftIcon size={20} />
          <span>Назад</span>
        </button>
      )}
      <Typography.Headline variant="large-strong" asChild>
        <h1 ref={heading} tabIndex={-1} className="screen-title">
          {title}
        </h1>
      </Typography.Headline>
      {subtitle && <p className="screen-subtitle">{subtitle}</p>}
    </header>
  );
}

export function Skeleton({
  height = 16,
  width = "100%",
  radius = 8,
}: {
  height?: number;
  width?: number | string;
  radius?: number;
}) {
  return (
    <span
      aria-hidden="true"
      className="skeleton"
      style={{ height, width, borderRadius: radius }}
    />
  );
}
export function SkeletonCards({
  count = 3,
  height = 92,
}: {
  count?: number;
  height?: number;
}) {
  return (
    <div className="stack" aria-busy="true" aria-label="Загрузка">
      {Array.from({ length: count }, (_, index) => (
        <div
          className="card skeleton-card"
          key={index}
          style={{ minHeight: height }}
        >
          <Skeleton width="65%" height={18} />
          <Skeleton width="45%" height={14} />
        </div>
      ))}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  title,
  audience = "student",
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  audience?: "student" | "teacher";
}) {
  const copy = describeError(error, audience);
  return (
    <div className="state" role="alert">
      <div className="state-icon" aria-hidden="true">
        <ChecksIcon size={28} />
      </div>
      <h2 className="state-title">{title ?? copy.title}</h2>
      <p className="state-text">{copy.text}</p>
      {copy.retry && onRetry && (
        <Action size="medium" onClick={onRetry}>
          Повторить загрузку
        </Action>
      )}
    </div>
  );
}

export function InlineError({
  children,
  onRetry,
  loading = false,
  label = "Повторить загрузку",
}: {
  children: ReactNode;
  onRetry: () => void;
  loading?: boolean;
  label?: string;
}) {
  return (
    <div className="inline-error">
      <p role="alert">{children}</p>
      <Action
        size="medium"
        variant="secondary"
        stretched
        loading={loading}
        onClick={onRetry}
      >
        {label}
      </Action>
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
      <h2 className="state-title">{title}</h2>
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
