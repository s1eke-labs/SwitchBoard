import { FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Activity, Eye, Loader2 } from "lucide-react";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { api } from "@/lib/api";
import { useI18n } from "@/i18n";
import { formatAppError } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function LoginPage({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const { t } = useI18n();
  const login = useMutation({
    mutationFn: () => api.login(password),
    onSuccess: onDone,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate();
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border bg-white p-5 shadow-soft">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Activity size={20} />
            </div>
            <div>
              <h1 className="text-xl font-bold">SwitchBoard</h1>
              <p className="text-sm text-muted-foreground">{t("login.subtitle")}</p>
            </div>
          </div>
          <LanguageSwitcher />
        </div>
        <Input
          autoFocus
          type="password"
          placeholder={t("login.passwordPlaceholder")}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {login.error ? <p className="mt-3 text-sm text-destructive">{formatAppError(login.error)}</p> : null}
        <Button className="mt-4 w-full" disabled={!password || login.isPending}>
          {login.isPending ? <Loader2 className="animate-spin" size={16} /> : <Eye size={16} />}
          {t("login.signIn")}
        </Button>
      </form>
    </main>
  );
}
