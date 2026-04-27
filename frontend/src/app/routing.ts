import { useCallback, useEffect, useState } from "react";

export type AppRoute =
  | { page: "dashboard" }
  | { page: "sessions"; threadId: string | null }
  | { page: "requestLogs" };

export function parseRoute(pathname = window.location.pathname): AppRoute {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] === "sessions") {
    const rawThreadId = segments.slice(1).join("/");
    return { page: "sessions", threadId: rawThreadId ? decodeURIComponent(rawThreadId) : null };
  }
  if (segments[0] === "request-logs") {
    return { page: "requestLogs" };
  }
  return { page: "dashboard" };
}

export function sessionPath(threadId: string) {
  return `/sessions/${encodeURIComponent(threadId)}`;
}

export function useRoute() {
  const [route, setRoute] = useState<AppRoute>(() => parseRoute());

  useEffect(() => {
    function handlePopState() {
      setRoute(parseRoute());
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = useCallback((path: string, replace = false) => {
    if (path === `${window.location.pathname}${window.location.search}${window.location.hash}`) return;
    if (replace) {
      window.history.replaceState(null, "", path);
    } else {
      window.history.pushState(null, "", path);
    }
    setRoute(parseRoute());
  }, []);

  return { route, navigate };
}
