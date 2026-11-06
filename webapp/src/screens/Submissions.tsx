import { CellList, CellSimple, Spinner } from "@maxhub/max-ui";
import { useState } from "react";

import { api } from "../api";
import type { Page, Submission } from "../api/types";
import { relativeDate } from "../format";
import { describeSubmission } from "../status";
import { useLoader } from "../hooks";
import { navigate } from "../router";
import {
  Action,
  ChatAction,
  EmptyState,
  ErrorState,
  InlineError,
  Screen,
  ScreenHeader,
  SkeletonCards,
} from "../ui/common";
import { CameraIcon, CheckIcon, CrossIcon } from "../ui/icons";

function StatusIcon({ item }: { item: Submission }) {
  const { tone } = describeSubmission(item);
  if (item.status === "queued" || item.status === "processing") {
    return (
      <span className="status-icon status-accent">
        <Spinner size={20} appearance="themed" />
      </span>
    );
  }
  return (
    <span className={`status-icon status-${tone}`} aria-hidden="true">
      {tone === "solid" ? (
        <CheckIcon size={20} />
      ) : tone === "weak" ? (
        <CrossIcon size={20} />
      ) : (
        "?"
      )}
    </span>
  );
}

function History({ first }: { first: Page<Submission> }) {
  const [pages, setPages] = useState<Page<Submission>[]>([first]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState(false);
  const items = pages.flatMap((page) => page.items);
  const cursor = pages.at(-1)?.next_cursor ?? null;

  const loadMore = () => {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    setMoreError(false);
    api.submissions(cursor).then(
      (page) => {
        setPages((current) => [...current, page]);
        setLoadingMore(false);
      },
      () => {
        setMoreError(true);
        setLoadingMore(false);
      },
    );
  };

  return (
    <div className="stack">
      <CellList mode="island" filled>
        {items.map((item) => (
          <CellSimple
            key={item.id}
            innerClassNames={{
              title: "history-title",
              subtitle: "history-subtitle",
            }}
            as="button"
            showChevron
            before={<StatusIcon item={item} />}
            title={item.topic_title ?? "Решение"}
            subtitle={`${describeSubmission(item).label} · ${relativeDate(item.created_at)}`}
            onClick={() => {
              navigate({ name: "submission", id: item.id });
            }}
          />
        ))}
      </CellList>
      {cursor && (
        <>
          {moreError ? (
            <InlineError onRetry={loadMore} loading={loadingMore}>
              Не удалось загрузить следующие разборы.
            </InlineError>
          ) : (
            <Action
              size="medium"
              variant="secondary"
              stretched
              loading={loadingMore}
              onClick={loadMore}
            >
              Показать ещё
            </Action>
          )}
        </>
      )}
    </div>
  );
}

export function SubmissionsScreen() {
  const page = useLoader("submissions", () => api.submissions());
  return (
    <Screen label="Разборы">
      <ScreenHeader
        title="Разборы"
        subtitle="Решения и подсказки из личного чата"
      />
      {page.state === "loading" && <SkeletonCards count={5} height={64} />}
      {page.state === "error" && (
        <ErrorState error={page.error} onRetry={page.reload} />
      )}
      {page.state === "ready" &&
        (page.data.items.length === 0 ? (
          <EmptyState
            icon={<CameraIcon size={28} />}
            title="Разборов пока нет"
            action={<ChatAction primary />}
          >
            <p>
              Отправь фото решения боту в личный чат. Здесь можно будет
              вернуться к результату проверки и подсказке.
            </p>
          </EmptyState>
        ) : (
          <History first={page.data} />
        ))}
    </Screen>
  );
}
