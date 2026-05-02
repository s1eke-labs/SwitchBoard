import * as React from "react";
import { CloseButton as HeroCloseButton, type CloseButtonProps as HeroCloseButtonProps } from "@heroui/react";
import { cn } from "@/lib/utils";

export const CloseButton = React.forwardRef<HTMLButtonElement, HeroCloseButtonProps>(
  ({ className, ...props }, ref) => {
    return (
      <HeroCloseButton
        ref={ref}
        className={cn("h-9 w-9 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground", className)}
        {...props}
      />
    );
  },
);
CloseButton.displayName = "CloseButton";
