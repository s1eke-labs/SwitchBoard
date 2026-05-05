/* eslint-disable react-refresh/only-export-components */
import * as React from "react";
import { ListBox as HeroListBox, Select as HeroSelect, type ListBoxItemProps, type ListBoxProps } from "@heroui/react";
import { cn } from "@/lib/utils";

type SelectRootProps = React.ComponentProps<typeof HeroSelect>;
type SelectTriggerProps = React.ComponentProps<typeof HeroSelect.Trigger>;
type SelectValueProps = React.ComponentProps<typeof HeroSelect.Value>;
type SelectIndicatorProps = React.ComponentProps<typeof HeroSelect.Indicator>;
type SelectPopoverProps = React.ComponentProps<typeof HeroSelect.Popover>;

function SelectRoot({ className, fullWidth = true, variant = "primary", ...props }: SelectRootProps) {
  return <HeroSelect className={cn(className)} fullWidth={fullWidth} variant={variant} {...props} />;
}

function SelectTrigger({ className, ...props }: SelectTriggerProps) {
  return (
    <HeroSelect.Trigger
      className={cn(
        "h-9 rounded-md border bg-white px-3 text-sm font-semibold shadow-none transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

function SelectValue({ className, ...props }: SelectValueProps) {
  return <HeroSelect.Value className={cn("min-w-0 truncate", className)} {...props} />;
}

function SelectIndicator({ className, ...props }: SelectIndicatorProps) {
  return <HeroSelect.Indicator className={cn("shrink-0 text-muted-foreground", className)} {...props} />;
}

function SelectPopover({ className, placement = "bottom end", ...props }: SelectPopoverProps) {
  return <HeroSelect.Popover className={cn("max-h-72 overflow-auto rounded-lg border bg-white p-2 shadow-soft", className)} placement={placement} {...props} />;
}

function SelectListBox<T extends object>({ className, variant = "default", ...props }: ListBoxProps<T>) {
  return <HeroListBox className={cn("space-y-1 outline-none", className)} variant={variant} {...props} />;
}

function SelectItem({ className, ...props }: ListBoxItemProps) {
  return (
    <HeroListBox.Item
      className={cn(
        "flex min-h-8 items-center rounded-md px-2 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-muted selected:bg-foreground selected:text-white",
        className,
      )}
      {...props}
    />
  );
}

export const Select = Object.assign(SelectRoot, {
  Trigger: SelectTrigger,
  Value: SelectValue,
  Indicator: SelectIndicator,
  Popover: SelectPopover,
  ListBox: SelectListBox,
  Item: SelectItem,
});
