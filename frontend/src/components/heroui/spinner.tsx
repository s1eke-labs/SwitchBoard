import { Spinner as HeroSpinner, type SpinnerProps as HeroSpinnerProps } from "@heroui/react";
import { cn } from "@/lib/utils";

export function Spinner({ className, color = "current", size = "sm", ...props }: HeroSpinnerProps) {
  return <HeroSpinner className={cn("shrink-0", className)} color={color} size={size} {...props} />;
}
