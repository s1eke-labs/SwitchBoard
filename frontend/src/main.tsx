import React from "react";
import ReactDOM from "react-dom/client";
import { Toast, toastQueue } from "@heroui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import { I18nProvider, initializeLocale } from "./i18n";
import "./index.css";

type ToastQueueWithWrapUpdate = {
  wrapUpdate?: (fn: () => void) => void;
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

const heroUIToastQueue = toastQueue.getQueue() as unknown as ToastQueueWithWrapUpdate;
heroUIToastQueue.wrapUpdate = (fn) => fn();

initializeLocale();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <App />
          <Toast.Provider maxVisibleToasts={4} placement="top" width={420} />
        </QueryClientProvider>
      </I18nProvider>
    </AppErrorBoundary>
  </React.StrictMode>,
);
