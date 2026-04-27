import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

type AppErrorBoundaryProps = {
  children: ReactNode;
};

type AppErrorBoundaryState = {
  hasError: boolean;
};

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Unhandled application error", error, errorInfo);
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4">
        <Card className="w-full max-w-lg overflow-hidden">
          <CardHeader className="flex items-center gap-3 bg-orange-50/60">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-orange-100 text-orange-700">
              <AlertTriangle size={20} />
            </div>
            <div>
              <h1 className="text-lg font-bold">SwitchBoard hit an unexpected error</h1>
              <p className="text-sm text-muted-foreground">The app can recover by reloading cleanly.</p>
            </div>
          </CardHeader>
          <CardContent className="space-y-4 pt-4">
            <p className="text-sm leading-6 text-muted-foreground">
              A component crashed while rendering. Reload the application to rebuild the dashboard state.
            </p>
            <Button onClick={() => window.location.reload()}>
              <RefreshCw size={16} />
              Reload app
            </Button>
          </CardContent>
        </Card>
      </main>
    );
  }
}