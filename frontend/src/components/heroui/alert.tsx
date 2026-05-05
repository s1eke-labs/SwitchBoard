import * as React from "react";
import { Alert as HeroAlert } from "@heroui/react";
import { cn } from "@/lib/utils";

type AlertTone = "default" | "success" | "warning" | "danger";
type AlertProps = Omit<React.ComponentProps<typeof HeroAlert>, "status"> & {
  tone?: AlertTone;
};

const toneClassMap: Record<AlertTone, string> = {
  default: "border-border bg-muted text-muted-foreground",
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  warning: "border-orange-200 bg-orange-50 text-orange-800",
  danger: "border-destructive/30 bg-destructive/5 text-destructive",
};

const statusMap: Record<AlertTone, React.ComponentProps<typeof HeroAlert>["status"]> = {
  default: "default",
  success: "success",
  warning: "warning",
  danger: "danger",
};

export function Alert({ children, className, tone = "default", ...props }: AlertProps) {
  return (
    <HeroAlert className={cn("rounded-md border px-3 py-2 text-sm", toneClassMap[tone], className)} status={statusMap[tone]} {...props}>
      <HeroAlert.Content>
        <HeroAlert.Description>{children}</HeroAlert.Description>
      </HeroAlert.Content>
    </HeroAlert>
  );
}
