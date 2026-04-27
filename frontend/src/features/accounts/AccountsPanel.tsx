import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Download, Loader2, RefreshCw, Upload } from "lucide-react";
import { toast } from "sonner";
import { api, AccountDTO } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { AccountCard } from "@/features/accounts/AccountCard";

const COLLAPSED_VISIBLE_COUNT = 3;

export function AccountsPanel({ accounts }: { accounts: AccountDTO[] }) {
  const [expanded, setExpanded] = useState(false);
  const importInputRef = useRef<HTMLInputElement | null>(null);
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
    const targetName = targetAccount?.display_name ?? "account";
    const promise = switchAccount.mutateAsync(accountId);

    toast.promise(promise, {
      loading: `Switching to ${targetName}`,
      success: (result) => {
        if (result.error) {
          toast.warning("Scan warning", {
            description: result.error,
          });
        }
        return {
          message: "Account switched",
          description: `Switched to ${result.account.display_name}. Restart Codex for the change to take effect.`,
        };
      },
      error: (error) => ({
        message: "Switch failed",
        description: error instanceof Error ? error.message : "Unable to switch account.",
      }),
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
    const promise = exportConfig.mutateAsync().then((config) => {
      downloadConfigFile(config);
      return config;
    });

    toast.promise(promise, {
      loading: "Exporting config",
      success: (config) => ({
        message: "Config exported",
        description: `${config.accounts.length} account preferences saved.`,
      }),
      error: (error) => ({
        message: "Export failed",
        description: error instanceof Error ? error.message : "Unable to export config.",
      }),
    });
  }

  async function handleImportConfig(file: File) {
    try {
      const config = JSON.parse(await file.text());
      const result = await importConfig.mutateAsync(config);
      toast.success("Config imported", {
        description: `${result.imported} imported (${result.created} created, ${result.updated} updated).`,
      });
    } catch (error) {
      toast.error("Import failed", {
        description: error instanceof Error ? error.message : "Unable to import config.",
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
              <h2 className="text-2xl font-bold">Accounts</h2>
              <p className="truncate text-sm text-muted-foreground">{current?.display_name ?? "No current account"}</p>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {hasHiddenAccounts ? (
                <Button
                  aria-label={expanded ? "Collapse accounts" : "Expand accounts"}
                  title={expanded ? "Collapse accounts" : "Expand accounts"}
                  size="icon"
                  variant="secondary"
                  onClick={() => setExpanded((value) => !value)}
                >
                  {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </Button>
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
              <Button
                aria-label="Import config"
                title="Import config"
                size="icon"
                variant="secondary"
                onClick={() => importInputRef.current?.click()}
                disabled={importConfig.isPending}
              >
                {importConfig.isPending ? <Loader2 className="animate-spin" size={16} /> : <Upload size={16} />}
              </Button>
              <Button
                aria-label="Export config"
                title="Export config"
                size="icon"
                variant="secondary"
                onClick={handleExportConfig}
                disabled={exportConfig.isPending}
              >
                {exportConfig.isPending ? <Loader2 className="animate-spin" size={16} /> : <Download size={16} />}
              </Button>
              <Button onClick={() => scan.mutate()} disabled={scan.isPending}>
                {scan.isPending ? <Loader2 className="animate-spin" size={16} /> : <RefreshCw size={16} />}
                Scan
              </Button>
            </div>
          </div>
          {scan.data?.error ? (
            <div className="rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-sm text-orange-800">{scan.data.error}</div>
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
