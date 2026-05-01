import { CloseButton as HeroCloseButton, type CloseButtonProps as HeroCloseButtonProps } from "@heroui/react";
import { cn } from "@/lib/utils";

export function CloseButton({ className, ...props }: HeroCloseButtonProps) {
  return <HeroCloseButton className={cn("h-9 w-9 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground", className)} {...props} />;
}
