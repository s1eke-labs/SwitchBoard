import { FormEvent, useState } from "react";
import { Check, Clock, Loader2, LogIn, Pencil, Trash2, X } from "lucide-react";
import { AccountDTO, LimitDTO } from "@/lib/api";
import { cn, formatPercent, formatTime, shortId } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

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

export function AccountCard({
  account,
  onHide,
  onRename,
  onSwitch,
  renaming,
  switching,
  expanded,
}: {
  account: AccountDTO;
  onHide: (id: string) => void;
  onRename: (id: string, customName: string | null) => Promise<unknown>;
  onSwitch: (id: string) => void;
  renaming: boolean;
  switching: boolean;
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

  const showUserName = Boolean(account.user_name && account.user_name !== account.display_name);
  const actionButtonClass = "h-8 w-8";
  const iconSize = 15;

  return (
    <Card className={cn("h-full min-h-0 overflow-hidden", account.current && "border-blue-300 bg-blue-50/40")}>
      <CardContent className={cn("flex h-full min-h-0 flex-col", expanded ? "p-4" : "p-3.5")}>
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            {isEditing ? (
              <form onSubmit={saveName} className="flex min-w-0 flex-wrap items-center gap-2">
                <Input
                  autoFocus
                  className="h-8 w-44 max-w-full"
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
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <h3 className="min-w-0 truncate text-base font-bold">{account.display_name}</h3>
                {account.current ? <Badge tone="blue">Current</Badge> : null}
                {account.expired ? <Badge tone="orange">Expired</Badge> : null}
                {showUserName ? <Badge tone="neutral">{account.user_name}</Badge> : null}
                {account.plan_type ? <Badge tone="neutral">{account.plan_type}</Badge> : null}
              </div>
            )}
            <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{shortId(account.account_id)}</p>
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
        <div className="mt-auto">
          <div className="grid gap-3">
            <LimitMeter label="5h remaining" limit={account.five_hour} />
            <LimitMeter label="Weekly remaining" limit={account.weekly} />
          </div>
        </div>
        {account.last_error ? (
          <div className="mt-2 truncate text-xs text-orange-700">
            Last scan failed{account.failed_scan_count ? ` x${account.failed_scan_count}` : ""}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
