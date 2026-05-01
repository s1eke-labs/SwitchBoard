import { Checkbox as HeroCheckbox, type CheckboxProps as HeroCheckboxProps } from "@heroui/react";
import { cn } from "@/lib/utils";

export function Checkbox({ className, ...props }: HeroCheckboxProps) {
  return <HeroCheckbox className={cn(className)} {...props} />;
}
