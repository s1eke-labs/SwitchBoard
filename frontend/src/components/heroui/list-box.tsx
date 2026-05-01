/* eslint-disable react-refresh/only-export-components */
import * as React from "react";
import { ListBox as HeroListBox, type ListBoxItemProps, type ListBoxProps } from "@heroui/react";
import { cn } from "@/lib/utils";

function ListBoxRoot<T extends object>({ className, variant = "default", ...props }: ListBoxProps<T>) {
  return <HeroListBox className={cn("outline-none", className)} variant={variant} {...props} />;
}

function ListBoxItem({ className, ...props }: ListBoxItemProps) {
  return (
    <HeroListBox.Item
      className={cn(
        "rounded-lg border bg-white outline-none transition-colors hover:bg-muted/40 selected:border-blue-200 selected:bg-blue-50/80 selected:ring-1 selected:ring-blue-100",
        className,
      )}
      {...props}
    />
  );
}

export const ListBox = Object.assign(ListBoxRoot, {
  Item: ListBoxItem,
});
