import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Download, RefreshCw, Upload } from "lucide-react";
import { toast } from "@heroui/react";
import { api, AccountDTO } from "@/lib/api";
import { useI18n } from "@/i18n";
import { formatAppError, formatIssueMessage } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { Alert } from "@/components/heroui/alert";
import { Button } from "@/components/heroui/button";
import { Spinner } from "@/components/heroui/spinner";
import { Toolbar } from "@/components/heroui/toolbar";
import { Tooltip } from "@/components/heroui/tooltip";
import { AccountCard } from "@/features/accounts/AccountCard";

const COLLAPSED_VISIBLE_COUNT = 3;

export function AccountsPanel({ accounts }: { accounts: AccountDTO[] }) {
  const [expanded, setExpanded] = useState(false);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const scan = useMutation({
    mutationFn: api.scan,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const switchAccount = useMutation({
    mutationFn: api.switchAccount,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const hide = useMutation({
    mutationFn: api.hideAccount,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const rename = useMutation({
    mutationFn: ({ accountId, customName }: { accountId: string; customName: string | null }) =>
      api.renameAccount(accountId, customName),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const exportConfig = useMutation({
    mutationFn: api.exportConfig,
  });
  const importConfig = useMutation({
    mutationFn: api.importConfig,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const current = accounts.find((account) => account.current);
  const hasHiddenAccounts = accounts.length > COLLAPSED_VISIBLE_COUNT;
  const visibleAccounts = expanded ? accounts : accounts.slice(0, COLLAPSED_VISIBLE_COUNT);

  function handleSwitch(accountId: string) {
    const targetAccount = accounts.find((account) => account.account_id === accountId);
    const targetName = targetAccount?.display_name ?? t("accounts.defaultName");
    const toastId = toast(t("accounts.switchingTo", { name: targetName }), { isLoading: true });
    const promise = switchAccount.mutateAsync(accountId);

    promise
      .then((result) => {
        toast.close(toastId);
        if (result.warning) {
          toast.warning(t("accounts.scanWarningTitle"), {
            description: formatIssueMessage(result.warning) ?? result.warning.message,
          });
        }
        toast.success(t("accounts.accountSwitched"), {
          description: t("accounts.accountSwitchedDescription", { name: result.account.display_name }),
        });
      })
      .catch((error) => {
        toast.close(toastId);
        toast.danger(t("accounts.switchFailed"), {
          description: error instanceof Error ? formatAppError(error) : t("accounts.switchFailedFallback"),
        });
      });
  }

  function configFileName() {
    const value = new Date();
    const pad = (part: number) => String(part).padStart(2, "0");
    return `switchboard-config-${value.getFullYear()}${pad(value.getMonth() + 1)}${pad(value.getDate())}-${pad(value.getHours())}${pad(value.getMinutes())}${pad(value.getSeconds())}.json`;
  }

  function downloadConfigFile(config: unknown) {
    const blob = new Blob([`${JSON.stringify(config, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = configFileName();
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function handleExportConfig() {
    const toastId = toast(t("accounts.exportingConfig"), { isLoading: true });
    const promise = exportConfig.mutateAsync().then((config) => {
      downloadConfigFile(config);
      return config;
    });

    promise
      .then((config) => {
        toast.close(toastId);
        toast.success(t("accounts.configExported"), {
          description: t("accounts.configExportedDescription", { count: config.accounts.length }),
        });
      })
      .catch((error) => {
        toast.close(toastId);
        toast.danger(t("accounts.exportFailed"), {
          description: error instanceof Error ? formatAppError(error) : t("accounts.exportFailedFallback"),
        });
      });
  }

  async function handleImportConfig(file: File) {
    try {
      const config = JSON.parse(await file.text());
      const result = await importConfig.mutateAsync(config);
      toast.success(t("accounts.configImported"), {
        description: t("accounts.configImportedDescription", {
          imported: result.imported,
          created: result.created,
          updated: result.updated,
        }),
      });
    } catch (error) {
      toast.danger(t("accounts.importFailed"), {
        description: error instanceof Error ? formatAppError(error) : t("accounts.importFailedFallback"),
      });
    }
  }

  useEffect(() => {
    if (!hasHiddenAccounts) setExpanded(false);
  }, [hasHiddenAccounts]);

  return (
    <section className="h-full min-h-0">
      <div
        className={cn(
          "z-20 flex min-h-0 flex-col overflow-hidden rounded-lg border bg-white shadow-soft",
          expanded ? "absolute inset-x-4 bottom-4 top-4 p-5 ring-1 ring-border" : "relative h-full p-4",
        )}
      >
        <div className={cn("flex min-h-0 flex-1 flex-col", expanded ? "gap-5" : "gap-3")}>
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-2xl font-bold">{t("accounts.title")}</h2>
              <p className="truncate text-sm text-muted-foreground">{current?.display_name ?? t("accounts.noCurrentAccount")}</p>
            </div>
            <Toolbar aria-label={t("accounts.title")}>
              {hasHiddenAccounts ? (
                <Tooltip content={expanded ? t("accounts.collapse") : t("accounts.expand")}>
                  <Button
                    aria-label={expanded ? t("accounts.collapse") : t("accounts.expand")}
                    size="icon"
                    variant="secondary"
                    onClick={() => setExpanded((value) => !value)}
                  >
                    {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </Button>
                </Tooltip>
              ) : null}
              <input
                ref={importInputRef}
                type="file"
                className="hidden"
                accept="application/json,.json"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void handleImportConfig(file);
                }}
              />
              <Tooltip content={t("accounts.importConfig")}>
                <Button
                  aria-label={t("accounts.importConfig")}
                  size="icon"
                  variant="secondary"
                  onClick={() => importInputRef.current?.click()}
                  disabled={importConfig.isPending}
                >
                  {importConfig.isPending ? <Spinner /> : <Upload size={16} />}
                </Button>
              </Tooltip>
              <Tooltip content={t("accounts.exportConfig")}>
                <Button
                  aria-label={t("accounts.exportConfig")}
                  size="icon"
                  variant="secondary"
                  onClick={handleExportConfig}
                  disabled={exportConfig.isPending}
                >
                  {exportConfig.isPending ? <Spinner /> : <Download size={16} />}
                </Button>
              </Tooltip>
              <Button onClick={() => scan.mutate()} disabled={scan.isPending}>
                {scan.isPending ? <Spinner /> : <RefreshCw size={16} />}
                {t("accounts.scan")}
              </Button>
            </Toolbar>
          </div>
          {scan.data?.warning ? (
            <Alert tone="warning">
              {formatIssueMessage(scan.data.warning) ?? scan.data.warning.message}
            </Alert>
          ) : null}
          <div className={cn("min-h-0", expanded ? "flex-1 overflow-y-auto pr-2" : "flex-1 overflow-hidden")}>
            <div className={cn("grid grid-cols-3 gap-4", !expanded && "h-full auto-rows-fr")}>
              {visibleAccounts.map((account) => (
                <AccountCard
                  key={account.account_id}
                  account={account}
                  expanded={expanded}
                  onHide={(id) => hide.mutate(id)}
                  onRename={(id, customName) => rename.mutateAsync({ accountId: id, customName })}
                  onSwitch={handleSwitch}
                  renaming={rename.isPending && rename.variables?.accountId === account.account_id}
                  switching={switchAccount.isPending && switchAccount.variables === account.account_id}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
