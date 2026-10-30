import type { ComponentType } from "react";

import { haptics } from "../max";
import { navigate, type Tab } from "../router";
import { BookIcon, ChartIcon, ChecksIcon, MapIcon } from "./icons";

const TABS: { tab: Tab; label: string; icon: ComponentType<{ size?: number }> }[] = [
  { tab: "map", label: "Карта", icon: MapIcon },
  { tab: "submissions", label: "Разборы", icon: ChecksIcon },
  { tab: "class", label: "Класс", icon: BookIcon },
  { tab: "teacher", label: "Учитель", icon: ChartIcon },
];

export function TabBar({ active, showTeacher }: { active: Tab; showTeacher: boolean }) {
  const tabs = showTeacher ? TABS : TABS.filter((item) => item.tab !== "teacher");
  return (
    <nav className="tabbar" aria-label="Разделы">
      {tabs.map(({ tab, label, icon: TabIcon }) => {
        const selected = tab === active;
        return (
          <button
            key={tab}
            type="button"
            className={selected ? "tab tab-active" : "tab"}
            aria-current={selected ? "page" : undefined}
            onClick={() => {
              if (!selected) {
                haptics.selection();
                navigate({ name: tab }, { replace: true });
              }
            }}
          >
            <TabIcon size={24} />
            <span className="tab-label">{label}</span>
          </button>
        );
      })}
    </nav>
  );
}
