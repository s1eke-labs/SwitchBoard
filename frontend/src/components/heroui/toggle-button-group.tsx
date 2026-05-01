import * as React from "react";
import { ToggleButton as HeroToggleButton, ToggleButtonGroup as HeroToggleButtonGroup } from "@heroui/react";
import { cn } from "@/lib/utils";

export type SegmentedControlOption<T extends string> = {
  value: T;
  label: React.ReactNode;
  disabled?: boolean;
};

type SegmentedControlProps<T extends string> = {
  value: T;
  options: readonly SegmentedControlOption<T>[];
  "aria-label": string;
  className?: string;
  disabled?: boolean;
  onChange: (value: T) => void;
};

export function ToggleButtonGroup({ className, isDetached = true, size = "sm", ...props }: React.ComponentProps<typeof HeroToggleButtonGroup>) {
  return (
    <HeroToggleButtonGroup
      className={cn("rounded-md border bg-white p-1", className)}
      isDetached={isDetached}
      size={size}
      {...props}
    />
  );
}

export function ToggleButton({ className, variant = "ghost", ...props }: React.ComponentProps<typeof HeroToggleButton>) {
  return (
    <HeroToggleButton
      className={cn(
        "h-8 min-w-12 rounded-sm px-3 text-sm font-semibold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground selected:bg-foreground selected:text-white selected:hover:bg-foreground",
        className,
      )}
      variant={variant}
      {...props}
    />
  );
}

export function SegmentedControl<T extends string>({
  value,
  options,
  "aria-label": ariaLabel,
  className,
  disabled,
  onChange,
}: SegmentedControlProps<T>) {
  return (
    <ToggleButtonGroup
      aria-label={ariaLabel}
      selectionMode="single"
      disallowEmptySelection
      selectedKeys={[value]}
      isDisabled={disabled}
      className={className}
      onSelectionChange={(keys) => {
        const nextValue = Array.from(keys)[0];
        if (typeof nextValue === "string") onChange(nextValue as T);
      }}
    >
      {options.map((option) => (
        <ToggleButton key={option.value} id={option.value} isDisabled={option.disabled}>
          {option.label}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}
