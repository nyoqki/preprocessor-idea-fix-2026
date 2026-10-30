import { Button, Input } from "@maxhub/max-ui";
import { useState, type ReactNode } from "react";

import { api } from "../api";
import type { Material, MaterialPage } from "../api/types";
import { relativeDate } from "../format";
import { useDebounced, useLoader } from "../hooks";
import { Chip, EmptyState, ErrorState, Screen, ScreenHeader, SkeletonCards } from "../ui/common";
import { BookIcon, SearchIcon } from "../ui/icons";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlight(text: string, query: string): ReactNode {
  const needle = query.trim();
  if (!needle) return text;
  const parts = text.split(new RegExp(`(${escapeRegExp(needle)})`, "gi"));
  return parts.map((part, index) =>
    index % 2 === 1 ? <mark key={index}>{part}</mark> : part,
  );
}

function MaterialCard({ item, query }: { item: Material; query: string }) {
  return (
    <article className="card material">
      <h3 className="material-title">{highlight(item.title ?? "Материал класса", query)}</h3>
      {item.snippet && <p className="material-snippet">{highlight(item.snippet, query)}</p>}
      <div className="material-meta">
        {item.topic_titles.map((title) => (
          <Chip key={title} tone="neutral">
            {title}
          </Chip>
        ))}
        <span className="material-date">{relativeDate(item.created_at)}</span>
      </div>
    </article>
  );
}

function Results({ first, query }: { first: MaterialPage; query: string }) {
  const [pages, setPages] = useState<MaterialPage[]>([first]);
  const [loading, setLoading] = useState(false);
  const items = pages.flatMap((page) => page.items);
  const cursor = pages.at(-1)?.next_cursor ?? null;

  if (items.length === 0) {
    return (
      <EmptyState icon={<SearchIcon size={32} />} title="Ничего не нашёл">
        <p>
          {query
            ? `По запросу «${query}» в материалах класса пусто. Попробуй другое слово.`
            : "Учитель ещё не загрузил материалы. Как только появятся конспекты, они будут здесь."}
        </p>
      </EmptyState>
    );
  }
  return (
    <div className="stack">
      {items.map((item) => (
        <MaterialCard key={item.id} item={item} query={query} />
      ))}
      {cursor && (
        <Button
          size="medium"
          variant="secondary"
          stretched
          loading={loading}
          onClick={() => {
            setLoading(true);
            api.materials(query, cursor).then(
              (page) => {
                setPages((current) => [...current, page]);
                setLoading(false);
              },
              () => {
                setLoading(false);
              },
            );
          }}
        >
          Показать ещё
        </Button>
      )}
    </div>
  );
}

export function ClassMaterialsScreen({ className }: { className: string | null }) {
  const [text, setText] = useState("");
  const query = useDebounced(text.trim(), 350);
  const page = useLoader(`materials:${query}`, () => api.materials(query));

  let content: ReactNode;
  if (page.state === "loading") {
    content = <SkeletonCards count={3} height={110} />;
  } else if (page.state === "error") {
    content = <ErrorState error={page.error} onRetry={page.reload} />;
  } else if (!page.data.has_class) {
    content = (
      <EmptyState icon={<BookIcon size={32} />} title="Ты пока не в классе">
        <p>
          Попроси учителя добавить бота «Ясно» в чат класса или прислать приглашение — тогда здесь
          появятся конспекты и материалы.
        </p>
      </EmptyState>
    );
  } else {
    content = <Results key={query} first={page.data} query={query} />;
  }

  return (
    <Screen label="Класс">
      <ScreenHeader
        title={className ? `Класс ${className}` : "Класс"}
        subtitle="Конспекты и материалы, которые прислали в чат класса"
      />
      <form
        className="search"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
        }}
      >
        <Input
          type="search"
          inputMode="search"
          enterKeyHint="search"
          placeholder="Найти в материалах"
          aria-label="Поиск по материалам класса"
          value={text}
          maxLength={200}
          withClearButton
          iconBefore={<SearchIcon size={20} />}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
      </form>
      {content}
    </Screen>
  );
}
