import * as React from "react";
import { TextArea as HeroTextArea, type TextAreaProps as HeroTextAreaProps } from "@heroui/react";
import { cn } from "@/lib/utils";

export const TextArea = React.forwardRef<HTMLTextAreaElement, HeroTextAreaProps>(
  ({ className, fullWidth = true, variant = "primary", ...props }, ref) => (
    <HeroTextArea
      ref={ref}
      className={cn("w-full resize-none rounded-md border bg-white px-3 py-2 text-sm leading-6 shadow-none outline-none placeholder:text-muted-foreground", className)}
      fullWidth={fullWidth}
      variant={variant}
      {...props}
    />
  ),
);
TextArea.displayName = "TextArea";
