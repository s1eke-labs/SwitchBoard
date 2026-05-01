import { Toolbar as HeroToolbar, type ToolbarProps as HeroToolbarProps } from "@heroui/react";
import { cn } from "@/lib/utils";

export function Toolbar({ className, isAttached = false, ...props }: HeroToolbarProps) {
  return <HeroToolbar className={cn("flex shrink-0 flex-wrap items-center gap-2", className)} isAttached={isAttached} {...props} />;
}
