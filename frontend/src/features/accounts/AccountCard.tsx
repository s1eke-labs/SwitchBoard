import { FormEvent, useState } from "react";
import { Check, Clock, Loader2, LogIn, Pencil, Trash2, X } from "lucide-react";
import { AccountDTO, LimitDTO } from "@/lib/api";
import { cn, formatPercent, formatTime, shortId } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { AccountDensity } from "@/features/accounts/accountDisplay";

function LimitMeter({ label, limit }: { label: string; limit: LimitDTO | null }) {
  const remaining = limit?.remaining_percent ?? 100;
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
        <span className="font-semibold text-muted-foreground">{label}</span>
        <span className="font-bold">{formatPercent(remaining)}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full limit-bar" style={{ width: `${Math.max(0, Math.min(100, remaining))}%` }} />
      </div>
      <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
        <Clock size={12} />
        <span>{formatTime(limit?.resets_at)}</span>
      </div>
    </div>
  );
}

function LimitSummary({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md bg-muted px-2.5 py-2">
      <div className="truncate text-xs font-semibold text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-base font-bold leading-none">{value}</div>
    </div>
  );
}

export function AccountCard({
  account,
  onHide,
  onRename,
  onSwitch,
  renaming,
  switching,
  density,
  expanded,
}: {
  account: AccountDTO;
  onHide: (id: string) => void;
  onRename: (id: string, customName: string | null) => Promise<unknown>;
  onSwitch: (id: string) => void;
  renaming: boolean;
  switching: boolean;
  density: AccountDensity;
  expanded: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [draftName, setDraftName] = useState(account.custom_name ?? account.display_name);
  const [renameError, setRenameError] = useState<string | null>(null);

  function beginEditing() {
    setDraftName(account.custom_name ?? account.display_name);
    setRenameError(null);
    setIsEditing(true);
  }

  function cancelEditing() {
    setIsEditing(false);
    setRenameError(null);
  }

  async function saveName(event: FormEvent) {
    event.preventDefault();
    setRenameError(null);
    try {
      await onRename(account.account_id, draftName.trim() || null);
      setIsEditing(false);
    } catch (error) {
      setRenameError(error instanceof Error ? error.message : "Rename failed");
    }
  }

  const isLarge = density === "large";
  const isMedium = density === "medium";
  const isSmall = density === "small";
  const fiveHour = formatPercent(account.five_hour?.remaining_percent ?? 100);
  const weekly = formatPercent(account.weekly?.remaining_percent ?? 100);
  const showUserName = Boolean(account.user_name && account.user_name !== account.display_name);
  const actionButtonClass = isLarge ? undefined : "h-8 w-8";
  const iconSize = isLarge ? 16 : 15;

  return (
    <Card className={cn("h-full min-h-0 overflow-hidden", account.current && "border-blue-300 bg-blue-50/40")}>
      <CardContent
        className={cn(
          "flex h-full min-h-0 flex-col",
          isLarge ? (expanded ? "p-5" : "p-4") : isMedium ? (expanded ? "p-4" : "p-3.5") : expanded ? "p-3.5" : "p-3",
        )}
      >
        <div className={cn("flex items-start justify-between gap-3", isLarge ? (expanded ? "mb-5" : "mb-4") : isMedium ? "mb-3" : "mb-2.5")}>
          <div className="min-w-0 flex-1">
            {isEditing ? (
              <form onSubmit={saveName} className="flex min-w-0 flex-wrap items-center gap-2">
                <Input
                  autoFocus
                  className={isSmall ? "h-8 w-32 max-w-full" : isMedium ? "h-8 w-44 max-w-full" : "h-9 w-56 max-w-full"}
                  placeholder="Custom name"
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                />
                <Button
                  aria-label="Save name"
                  title="Save name"
                  size="icon"
                  className={actionButtonClass}
                  type="submit"
                  disabled={renaming}
                >
                  {renaming ? <Loader2 className="animate-spin" size={iconSize} /> : <Check size={iconSize} />}
                </Button>
                <Button
                  aria-label="Cancel rename"
                  title="Cancel rename"
                  size="icon"
                  className={actionButtonClass}
                  type="button"
                  variant="ghost"
                  onClick={cancelEditing}
                  disabled={renaming}
                >
                  <X size={iconSize} />
                </Button>
              </form>
            ) : (
              <div className={cn("flex min-w-0 flex-wrap items-center gap-2", isSmall && "gap-x-1.5 gap-y-1")}>
                <h3 className={cn("min-w-0 truncate font-bold", isSmall ? "text-sm" : "text-base")}>{account.display_name}</h3>
                {account.current ? <Badge tone="blue">Current</Badge> : null}
                {account.expired ? <Badge tone="orange">Expired</Badge> : null}
                {!isSmall && showUserName ? <Badge tone="neutral">{account.user_name}</Badge> : null}
                {!isSmall && account.plan_type ? <Badge tone="neutral">{account.plan_type}</Badge> : null}
              </div>
            )}
            {!isSmall ? <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{shortId(account.account_id)}</p> : null}
            {renameError ? <p className="mt-2 text-xs text-destructive">{renameError}</p> : null}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {!account.current ? (
              <Button
                aria-label="Switch account"
                title="Switch account"
                size="icon"
                variant="secondary"
                className={actionButtonClass}
                onClick={() => onSwitch(account.account_id)}
                disabled={switching}
              >
                {switching ? <Loader2 className="animate-spin" size={iconSize} /> : <LogIn size={iconSize} />}
              </Button>
            ) : null}
            {!isEditing ? (
              <Button
                aria-label="Rename account"
                title="Rename account"
                size="icon"
                variant="ghost"
                className={actionButtonClass}
                onClick={beginEditing}
              >
                <Pencil size={iconSize} />
              </Button>
            ) : null}
            {!account.current ? (
              <Button
                aria-label="Hide account"
                title="Hide account"
                size="icon"
                variant="ghost"
                className={actionButtonClass}
                onClick={() => onHide(account.account_id)}
                disabled={switching}
              >
                <Trash2 size={iconSize} />
              </Button>
            ) : null}
          </div>
        </div>
        {isSmall ? (
          <div className="mt-auto grid grid-cols-2 gap-2">
            <LimitSummary label="5h" value={fiveHour} />
            <LimitSummary label="Weekly" value={weekly} />
          </div>
        ) : (
          <div className={`grid ${isLarge ? "gap-4 sm:grid-cols-2" : "gap-3"}`}>
            <LimitMeter label="5h remaining" limit={account.five_hour} />
            <LimitMeter label="Weekly remaining" limit={account.weekly} />
          </div>
        )}
        {isLarge ? (
          <div className="mt-4 flex min-w-0 flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span className="truncate">Scanned {formatTime(account.last_scanned_at)}</span>
            {account.last_error ? (
              <span className="truncate text-orange-700">
                Last scan failed{account.failed_scan_count ? ` x${account.failed_scan_count}` : ""}
              </span>
            ) : null}
          </div>
        ) : account.last_error ? (
          <div className="mt-2 truncate text-xs text-orange-700">
            Last scan failed{account.failed_scan_count ? ` x${account.failed_scan_count}` : ""}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
