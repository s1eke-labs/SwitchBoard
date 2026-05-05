import * as React from "react";
import { SearchField as HeroSearchField } from "@heroui/react";
import { cn } from "@/lib/utils";

type SearchFieldProps = Omit<React.ComponentProps<typeof HeroSearchField>, "children"> & {
  inputClassName?: string;
  placeholder?: string;
};

export function SearchField({ className, inputClassName, placeholder, fullWidth = true, variant = "primary", ...props }: SearchFieldProps) {
  return (
    <HeroSearchField className={cn(className)} fullWidth={fullWidth} variant={variant} {...props}>
      <HeroSearchField.Group className="h-10 rounded-lg border bg-white px-3 shadow-none">
        <HeroSearchField.SearchIcon className="text-muted-foreground" />
        <HeroSearchField.Input className={cn("text-sm placeholder:text-muted-foreground", inputClassName)} placeholder={placeholder} />
        <HeroSearchField.ClearButton className="text-muted-foreground hover:text-foreground" />
      </HeroSearchField.Group>
    </HeroSearchField>
  );
}
