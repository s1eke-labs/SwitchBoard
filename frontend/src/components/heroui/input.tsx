import * as React from "react";
import { Input as HeroInput, type InputProps as HeroInputProps } from "@heroui/react";
import { cn } from "@/lib/utils";

export interface InputProps extends Omit<HeroInputProps, "fullWidth" | "variant"> {
  variant?: HeroInputProps["variant"];
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, variant = "primary", ...props }, ref) => (
    <HeroInput
      ref={ref}
      className={cn(
        "h-9 w-full rounded-md border bg-white px-3 text-sm shadow-none",
        className,
      )}
      fullWidth
      variant={variant}
      {...props}
    />
  ),
);
Input.displayName = "Input";
