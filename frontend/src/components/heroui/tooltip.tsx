import * as React from "react";
import { Tooltip as HeroTooltip } from "@heroui/react";
import { cn } from "@/lib/utils";

type TooltipProps = React.ComponentProps<typeof HeroTooltip> & {
  content: React.ReactNode;
  contentClassName?: string;
};

export function Tooltip({ children, content, contentClassName, ...props }: TooltipProps) {
  return (
    <HeroTooltip {...props}>
      <HeroTooltip.Trigger>{children}</HeroTooltip.Trigger>
      <HeroTooltip.Content className={cn("rounded-md border bg-foreground px-2 py-1 text-xs font-semibold text-white shadow-soft", contentClassName)}>
        {content}
      </HeroTooltip.Content>
    </HeroTooltip>
  );
}
