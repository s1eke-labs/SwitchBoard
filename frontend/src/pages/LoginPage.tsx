import { FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Activity, ArrowRight, KeyRound, Loader2, LockKeyhole, ShieldCheck } from "lucide-react";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { api } from "@/lib/api";
import { useI18n } from "@/i18n";
import { formatAppError } from "@/lib/errors";
import { Button } from "@/components/heroui/button";
import { Input } from "@/components/heroui/input";

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
    <main className="min-h-screen overflow-hidden bg-[#f8f7f5] text-foreground">
      <div className="mx-auto grid min-h-screen w-full max-w-6xl items-center gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[1.08fr_0.92fr] lg:gap-12 lg:px-8">
        <section className="order-2 space-y-6 lg:order-1">
          <div className="space-y-5">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-[#31302e] text-white shadow-soft">
                <Activity size={21} />
              </div>
              <div>
                <p className="text-sm font-semibold text-[#615d59]">{t("login.subtitle")}</p>
                <h1 className="text-4xl font-bold leading-none text-[#000000f2] sm:text-5xl">SwitchBoard</h1>
              </div>
            </div>
            <p className="max-w-xl text-lg leading-7 text-[#615d59]">{t("login.heroCopy")}</p>
          </div>

          <div className="rounded-lg border border-black/10 bg-white shadow-[0_4px_18px_rgba(0,0,0,0.04),0_2px_8px_rgba(0,0,0,0.03)]">
            <div className="flex items-center justify-between border-b border-black/10 px-4 py-3">
              <div className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-[#dd5b00]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[#a39e98]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[#2a9d99]" />
              </div>
              <div className="rounded-full bg-[#f2f9ff] px-2.5 py-1 text-xs font-semibold text-[#097fe8]">
                {t("login.previewBadge")}
              </div>
            </div>
            <div className="grid gap-4 p-4 sm:grid-cols-[0.9fr_1.1fr]">
              <div className="space-y-3 rounded-md bg-[#f6f5f4] p-3">
                <div className="flex items-center justify-between text-sm font-semibold">
                  <span>{t("accounts.current")}</span>
                  <span className="rounded-full bg-white px-2 py-0.5 text-xs text-[#2a9d99]">{t("login.previewOnline")}</span>
                </div>
                <div className="space-y-2">
                  <div className="h-2.5 rounded-full bg-[#31302e]" />
                  <div className="h-2.5 w-5/6 rounded-full bg-[#a39e98]/50" />
                  <div className="h-2.5 w-2/3 rounded-full bg-[#a39e98]/40" />
                </div>
                <div className="limit-bar h-2 rounded-full" />
              </div>

              <div className="grid gap-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-md border border-black/10 p-3">
                    <p className="text-xs font-medium text-[#615d59]">{t("nav.sessions")}</p>
                    <p className="mt-2 text-2xl font-bold leading-none">28</p>
                  </div>
                  <div className="rounded-md border border-black/10 p-3">
                    <p className="text-xs font-medium text-[#615d59]">{t("requestLogs.totalRequests")}</p>
                    <p className="mt-2 text-2xl font-bold leading-none">142</p>
                  </div>
                </div>
                <div className="rounded-md border border-black/10 p-3">
                  <div className="mb-2 flex items-center justify-between gap-3 text-xs font-semibold text-[#615d59]">
                    <span>{t("usage.title")}</span>
                    <span>{t("accounts.fiveHourRemaining")}</span>
                  </div>
                  <div className="grid grid-cols-[0.35fr_0.3fr_0.2fr_0.15fr] gap-1">
                    <span className="h-8 rounded-sm bg-[#0075de]" />
                    <span className="h-8 rounded-sm bg-[#2a9d99]" />
                    <span className="h-8 rounded-sm bg-[#dd5b00]" />
                    <span className="h-8 rounded-sm bg-[#a39e98]" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="order-1 lg:order-2">
          <form
            onSubmit={submit}
            className="mx-auto w-full max-w-md rounded-lg border border-black/10 bg-white p-5 shadow-[0_1px_3px_rgba(0,0,0,0.01),0_3px_7px_rgba(0,0,0,0.02),0_7px_15px_rgba(0,0,0,0.02),0_14px_28px_rgba(0,0,0,0.04),0_23px_52px_rgba(0,0,0,0.05)] sm:p-6"
          >
            <div className="mb-7 flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[#f2f9ff] text-[#097fe8]">
                  <KeyRound size={20} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-[#615d59]">{t("login.secureBadge")}</p>
                  <h2 className="text-2xl font-bold leading-tight text-[#000000f2]">{t("login.title")}</h2>
                </div>
              </div>
              <LanguageSwitcher />
            </div>

            <label className="mb-2 flex items-center gap-2 text-sm font-semibold text-[#31302e]" htmlFor="switchboard-password">
              <LockKeyhole size={16} />
              {t("login.passwordLabel")}
            </label>
            <Input
              id="switchboard-password"
              autoFocus
              type="password"
              placeholder={t("login.passwordPlaceholder")}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="h-11 rounded bg-white text-base"
            />
            {login.error ? (
              <p className="mt-3 rounded-md bg-orange-50 px-3 py-2 text-sm font-medium text-destructive" role="alert">
                {formatAppError(login.error)}
              </p>
            ) : null}
            <Button className="mt-5 h-11 w-full rounded bg-[#0075de] text-[15px] hover:bg-[#005bab]" disabled={!password || login.isPending}>
              {login.isPending ? <Loader2 className="animate-spin" size={17} /> : <ArrowRight size={17} />}
              {t("login.signIn")}
            </Button>

            <div className="mt-5 flex items-start gap-2 border-t border-black/10 pt-4 text-sm leading-5 text-[#615d59]">
              <ShieldCheck className="mt-0.5 shrink-0 text-[#2a9d99]" size={17} />
              <span>{t("login.securityNote")}</span>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}
