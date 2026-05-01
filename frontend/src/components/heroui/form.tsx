import { Form as HeroForm, type FormProps as HeroFormProps } from "@heroui/react";
import { cn } from "@/lib/utils";

export function Form({ className, ...props }: HeroFormProps) {
  return <HeroForm className={cn(className)} {...props} />;
}
