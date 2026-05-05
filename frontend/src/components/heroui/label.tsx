import { Label as HeroLabel, type LabelProps as HeroLabelProps } from "@heroui/react";
import { cn } from "@/lib/utils";

export function Label({ className, ...props }: HeroLabelProps) {
  return <HeroLabel className={cn("text-sm font-semibold", className)} {...props} />;
}
