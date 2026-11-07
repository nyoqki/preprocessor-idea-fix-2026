import { useEffect } from "react";

import { api, ApiError, isMock } from "./api";
import { useLoader, useOnline } from "./hooks";
import { observeViewport, ready, showBackButton, startParam } from "./max";
import { goBack, navigate, parentOf, routeFromStartParam, tabOf, useRoute } from "./router";
import { ClassMaterialsScreen } from "./screens/ClassMaterials";
import { GapMapScreen } from "./screens/GapMap";
import { QuizScreen } from "./screens/Quiz";
import { SubmissionDetailScreen } from "./screens/SubmissionDetail";
import { SubmissionsScreen } from "./screens/Submissions";
import { TeacherScreen } from "./screens/Teacher";
import { ErrorState, Screen, ScreenHeader, SkeletonCards } from "./ui/common";
import { TabBar } from "./ui/TabBar";

function openDeepLink(): void {
  if (window.location.hash.length > 1) return;
  const route = routeFromStartParam(startParam());
  if (route) {
    navigate(route, { replace: true });
  }
}

openDeepLink();

export function App() {
  const route = useRoute();
  const me = useLoader("me", () => api.me());
  const online = useOnline();
  const routeKey = JSON.stringify(route);

  useEffect(() => {
    ready();
    return observeViewport();
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [routeKey]);

  useEffect(() => {
    if (parentOf(route) === null) return;
    return showBackButton(() => {
      goBack(route);
    });
  }, [routeKey, route]);

  if (me.state === "loading")
    return (
      <div className="shell">
        <Screen label="Ясно">
          <SkeletonCards count={3} />
        </Screen>
      </div>
    );

  if (me.state === "error" && me.error instanceof ApiError && me.error.kind === "auth") {
    return (
      <div className="shell shell-focus">
        <Screen label="Ясно">
          <ScreenHeader title="Ясно" />
          <ErrorState error={me.error} />
        </Screen>
      </div>
    );
  }

  const profile = me.data;
  const isTeacher = profile?.role === "teacher";
  const tab = tabOf(route);

  let screen;
  if (me.state === "error") {
    screen = (
      <Screen label="Ясно">
        <ScreenHeader title="Ясно" />
        <ErrorState error={me.error} onRetry={me.reload} />
      </Screen>
    );
  } else {
    switch (route.name) {
      case "map":
        screen = <GapMapScreen me={profile} />;
        break;
      case "submissions":
        screen = <SubmissionsScreen />;
        break;
      case "submission":
        screen = <SubmissionDetailScreen key={route.id} id={route.id} />;
        break;
      case "quiz":
        screen = <QuizScreen key={route.id} id={route.id} />;
        break;
      case "class":
        screen = <ClassMaterialsScreen className={profile?.school_class?.title ?? null} />;
        break;
      case "teacher":
        screen =
          profile === null ? (
            <Screen label="Учитель">
              <SkeletonCards count={3} />
            </Screen>
          ) : isTeacher ? (
            <TeacherScreen />
          ) : (
            <Screen label="Учитель">
              <ScreenHeader title="Темы класса" />
              <ErrorState error={new ApiError("forbidden", 403, "teacher_only")} />
            </Screen>
          );
        break;
    }
  }

  return (
    <div className={route.name === "quiz" ? "shell shell-focus" : "shell"}>
      {!online && (
        <div className="offline" role="status">
          Нет интернета. Уже загруженные данные доступны, новые запросы могут не пройти.
        </div>
      )}
      {isMock && <div className="mock-badge">Ясно · демо-данные</div>}
      {screen}
      {route.name !== "quiz" && <TabBar active={tab} showTeacher={isTeacher} />}
    </div>
  );
}
