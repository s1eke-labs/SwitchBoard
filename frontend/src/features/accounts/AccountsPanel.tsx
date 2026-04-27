import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, LayoutGrid, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api, AccountDTO } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { AccountCard } from "@/features/accounts/AccountCard";
import {
  AccountDensity,
  accountDensityLabels,
  accountDensityOrder,
  accountGridClasses,
  collapsedRowsByDensity,
} from "@/features/accounts/accountDisplay";

export function AccountsPanel({ accounts }: { accounts: AccountDTO[] }) {
  const [expanded, setExpanded] = useState(false);
  const [density, setDensity] = useState<AccountDensity>("large");
  const [collapsedHeight, setCollapsedHeight] = useState(0);
  const [hasOverflowRow, setHasOverflowRow] = useState(false);
  const gridRef = useRef<HTMLDivElement | null>(null);
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
  const current = accounts.find((account) => account.current);
  const nextDensity = accountDensityOrder[(accountDensityOrder.indexOf(density) + 1) % accountDensityOrder.length];
  const densitySwitchLabel = `Accounts view: ${accountDensityLabels[density]}. Switch to ${accountDensityLabels[nextDensity]}`;
  const gridClass = accountGridClasses[density];
  const gridGapClass = expanded ? "gap-4" : density === "small" ? "gap-3" : "gap-4";
  const listStyle = expanded || collapsedHeight === 0 ? undefined : { maxHeight: `${collapsedHeight}px` };

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

  useLayoutEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    const target = grid;

    function measure() {
      const items = Array.from(target.children).filter((child): child is HTMLElement => child instanceof HTMLElement);
      if (!items.length) {
        setCollapsedHeight(0);
        setHasOverflowRow(false);
        return;
      }

      const rows: HTMLElement[][] = [];
      for (const item of items) {
        const row = rows.find((candidate) => Math.abs(candidate[0].offsetTop - item.offsetTop) < 4);
        if (row) {
          row.push(item);
        } else {
          rows.push([item]);
        }
      }

      const visibleRowCount = collapsedRowsByDensity[density];
      const visibleRows = rows.slice(0, visibleRowCount).flat();
      const firstTop = rows[0][0].offsetTop;
      const visibleBottom = Math.max(...visibleRows.map((item) => item.offsetTop + item.offsetHeight));
      setCollapsedHeight(Math.ceil(visibleBottom - firstTop));
      setHasOverflowRow(rows.length > visibleRowCount);
    }

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(target);
    for (const child of Array.from(target.children)) {
      if (child instanceof HTMLElement) observer.observe(child);
    }
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [accounts, density]);

  useEffect(() => {
    if (!hasOverflowRow) setExpanded(false);
  }, [hasOverflowRow]);

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
              {hasOverflowRow ? (
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
              <Button
                aria-label={densitySwitchLabel}
                title={densitySwitchLabel}
                size="icon"
                variant="secondary"
                onClick={() => setDensity(nextDensity)}
              >
                <LayoutGrid size={16} />
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
          <div className={cn("min-h-0 flex-1", expanded ? "overflow-y-auto pr-2" : "overflow-hidden")} style={listStyle}>
            <div ref={gridRef} className={cn("grid", gridClass, gridGapClass)}>
              {accounts.map((account) => (
                <AccountCard
                  key={account.account_id}
                  account={account}
                  density={density}
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
