import { FieldError as HeroFieldError, type FieldErrorProps as HeroFieldErrorProps } from "@heroui/react";
import { cn } from "@/lib/utils";

export function FieldError({ className, ...props }: HeroFieldErrorProps) {
  return <HeroFieldError className={cn("text-sm font-medium text-destructive", className)} {...props} />;
}
