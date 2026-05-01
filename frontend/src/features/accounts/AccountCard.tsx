import { FormEvent, useState } from "react";
import { Check, Clock, LogIn, Pencil, Trash2, X } from "lucide-react";
import { AccountDTO, LimitDTO } from "@/lib/api";
import { useI18n } from "@/i18n";
import { formatAppError } from "@/lib/errors";
import { cn, formatDuration, formatPercent, formatTime } from "@/lib/utils";
import { Alert } from "@/components/heroui/alert";
import { Badge } from "@/components/heroui/badge";
import { Button, type ButtonProps } from "@/components/heroui/button";
import { Card, CardContent } from "@/components/heroui/card";
import { Form } from "@/components/heroui/form";
import { Input } from "@/components/heroui/input";
import { Meter } from "@/components/heroui/meter";
import { Spinner } from "@/components/heroui/spinner";
import { Tooltip } from "@/components/heroui/tooltip";

function LimitMeter({ label, limit }: { label: string; limit: LimitDTO | null }) {
  const remaining = limit?.remaining_percent ?? 100;
  return (
    <Meter aria-label={label} minValue={0} maxValue={100} value={remaining}>
      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
        <span className="font-semibold text-muted-foreground">{label}</span>
        <Meter.Output>{formatPercent(remaining)}</Meter.Output>
      </div>
      <Meter.Track>
        <Meter.Fill />
      </Meter.Track>
      <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
        <Clock size={12} />
        <span>{formatTime(limit?.resets_at)}</span>
      </div>
    </Meter>
  );
}

function IconActionButton({ label, children, ...props }: ButtonProps & { label: string }) {
  return (
    <Tooltip content={label}>
      <Button aria-label={label} size="icon" {...props}>
        {children}
      </Button>
    </Tooltip>
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
              <Form onSubmit={saveName} className="flex min-w-0 flex-wrap items-center gap-2">
                <Input
                  autoFocus
                  className="h-8 w-44 max-w-full"
                  placeholder={t("accounts.customNamePlaceholder")}
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                />
                <IconActionButton
                  label={t("accounts.saveName")}
                  className={actionButtonClass}
                  type="submit"
                  disabled={renaming}
                >
                  {renaming ? <Spinner /> : <Check size={iconSize} />}
                </IconActionButton>
                <IconActionButton
                  label={t("accounts.cancelRename")}
                  className={actionButtonClass}
                  type="button"
                  variant="ghost"
                  onClick={cancelEditing}
                  disabled={renaming}
                >
                  <X size={iconSize} />
                </IconActionButton>
              </Form>
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
              <Alert tone="danger" className="mt-2 px-2 py-1 text-xs">
                {renameError instanceof Error ? formatAppError(renameError) : t("accounts.renameFailedFallback")}
              </Alert>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {!account.current ? (
              <IconActionButton
                label={t("accounts.switchAccount")}
                variant="secondary"
                className={actionButtonClass}
                onClick={() => onSwitch(account.account_id)}
                disabled={switching}
              >
                {switching ? <Spinner /> : <LogIn size={iconSize} />}
              </IconActionButton>
            ) : null}
            {!isEditing ? (
              <IconActionButton
                label={t("accounts.renameAccount")}
                variant="ghost"
                className={actionButtonClass}
                onClick={beginEditing}
              >
                <Pencil size={iconSize} />
              </IconActionButton>
            ) : null}
            {!account.current ? (
              <IconActionButton
                label={t("accounts.hideAccount")}
                variant="ghost"
                className={actionButtonClass}
                onClick={() => onHide(account.account_id)}
                disabled={switching}
              >
                <Trash2 size={iconSize} />
              </IconActionButton>
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
