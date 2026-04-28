import { FormEvent, useState } from "react";
import { Check, Clock, Loader2, LogIn, Pencil, Trash2, X } from "lucide-react";
import { AccountDTO, LimitDTO } from "@/lib/api";
import { useI18n } from "@/i18n";
import { formatAppError } from "@/lib/errors";
import { cn, formatDuration, formatPercent, formatTime } from "@/lib/utils";
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
  const { t } = useI18n();
  const [isEditing, setIsEditing] = useState(false);
  const [draftName, setDraftName] = useState(account.custom_name ?? account.display_name);
  const [renameError, setRenameError] = useState<unknown>(null);

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
      setRenameError(error);
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
                  placeholder={t("accounts.customNamePlaceholder")}
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                />
                <Button
                  aria-label={t("accounts.saveName")}
                  title={t("accounts.saveName")}
                  size="icon"
                  className={actionButtonClass}
                  type="submit"
                  disabled={renaming}
                >
                  {renaming ? <Loader2 className="animate-spin" size={iconSize} /> : <Check size={iconSize} />}
                </Button>
                <Button
                  aria-label={t("accounts.cancelRename")}
                  title={t("accounts.cancelRename")}
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
                {account.current ? <Badge tone="blue">{t("accounts.current")}</Badge> : null}
                {account.expired ? <Badge tone="orange">{t("accounts.expired")}</Badge> : null}
                {showUserName ? <Badge tone="neutral">{account.user_name}</Badge> : null}
                {account.plan_type ? <Badge tone="neutral">{account.plan_type}</Badge> : null}
              </div>
            )}
            {renameError ? (
              <p className="mt-2 text-xs text-destructive">
                {renameError instanceof Error ? formatAppError(renameError) : t("accounts.renameFailedFallback")}
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {!account.current ? (
              <Button
                aria-label={t("accounts.switchAccount")}
                title={t("accounts.switchAccount")}
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
                aria-label={t("accounts.renameAccount")}
                title={t("accounts.renameAccount")}
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
                aria-label={t("accounts.hideAccount")}
                title={t("accounts.hideAccount")}
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
            <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
              <Clock size={13} />
              <span>{t("accounts.usedFor", { duration: formatDuration(account.usage_seconds) })}</span>
            </div>
            <LimitMeter label={t("accounts.fiveHourRemaining")} limit={account.five_hour} />
            <LimitMeter label={t("accounts.weeklyRemaining")} limit={account.weekly} />
          </div>
        </div>
        {account.last_error ? (
          <div className="mt-2 truncate text-xs text-orange-700">
            {account.failed_scan_count
              ? t("accounts.lastScanFailedCount", { count: account.failed_scan_count })
              : t("accounts.lastScanFailed")}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
